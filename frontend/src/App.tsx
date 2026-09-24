import { useEffect, useMemo, useRef, useState } from "react";
import { tr, type Lang } from "./lib/i18n.ts";
import type { RecoResult, ScoredReco, SetupStatus } from "./lib/types.ts";
import {
  addToWatchlist,
  fetchAniListAuth,
  fetchAppUpdate,
  fetchHealth,
  fetchProfile,
  fetchSetupStatus,
  lookupMedia,
  postLocalMode,
  postSetup,
  startAniListLogin,
  streamRecommend,
  watchlistStatus,
  type AniListAuth,
  type AppUpdate,
  type LocalMode,
} from "./lib/api.ts";
// component and type share the name: the type is aliased
import { AniListAuth as AniListAuthPanel } from "./components/AniListAuth.tsx";
import { errorMessage } from "./lib/logic/errors.ts";
import { detectLang } from "./lib/logic/lang.ts";
import type { StreamPhase } from "./lib/logic/progress.ts";
import { score110 } from "./lib/logic/display.ts";
import {
  applyFilters,
  carouselPicks,
  formatsOf,
  gemsOf,
  heroPick,
  topGenres,
  topPicksOf,
  type SortKey,
} from "./lib/logic/recos.ts";
import { AvoidList } from "./components/AvoidList.tsx";
import { Carousel } from "./components/Carousel.tsx";
import { ChatPanel } from "./components/ChatPanel.tsx";
import { DetailDialog } from "./components/DetailDialog.tsx";
import { Hero } from "./components/Hero.tsx";
import { MediaCard } from "./components/MediaCard.tsx";
import { ProfileView } from "./components/ProfileView.tsx";
import { Rail } from "./components/Rail.tsx";
import { LoginModal } from "./components/LoginModal.tsx";
import { LlmSettings } from "./components/LlmSettings.tsx";
import { Progress } from "./components/Progress.tsx";
import { SetupWizard } from "./components/SetupWizard.tsx";
import { Topbar } from "./components/Topbar.tsx";
import { VIEW_ORDER, type View } from "./views/index.ts";

export function App() {
  const [lang, setLang] = useState<Lang>(() =>
    detectLang(localStorage.getItem("lang"), typeof navigator === "undefined" ? "" : navigator.language),
  );
  const [view, setView] = useState<View>(() => {
    const v = localStorage.getItem("alr-view");
    return VIEW_ORDER.includes(v as View) ? (v as View) : "home";
  });
  const [setup, setSetup] = useState<SetupStatus | null | "error">(null);
  const [llmOn, setLlmOn] = useState<boolean | null>(null);
  const [local, setLocal] = useState<LocalMode | null>(null);
  const [update, setUpdate] = useState<AppUpdate | null>(null);
  const [phase, setPhase] = useState<"idle" | StreamPhase | "recos">("idle");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [loginOpen, setLoginOpen] = useState(localStorage.getItem("username") === null);
  const [animeSearch, setAnimeSearch] = useState<{ q: string; busy: boolean; recos: ScoredReco[] | null }>({
    q: "",
    busy: false,
    recos: null,
  });
  const [result, setResult] = useState<RecoResult | null>(null);
  const [whySource, setWhySource] = useState<Record<number, "llm" | "local">>({});
  const [extraRecos, setExtraRecos] = useState<ScoredReco[]>([]);
  const langRef = useRef(lang);
  const [sort, setSort] = useState<SortKey>("final");
  const [gemsOnly, setGemsOnly] = useState(false);
  const [format, setFormat] = useState("all");
  const [genre, setGenre] = useState("all");
  const [dialog, setDialog] = useState<ScoredReco | null>(null);
  const lastView = useRef<View>("recos");
  // AniList OAuth: null until the first status fetch answers
  const [auth, setAuth] = useState<AniListAuth | null>(null);
  const [watch, setWatch] = useState<{ status: string | null; busy: boolean } | null>(null);

  useEffect(() => {
    fetchSetupStatus().then(setSetup).catch(() => setSetup("error"));
  }, []);

  // AniList OAuth status: once on mount, then only while a login flow is pending
  const pollRef = useRef(0);
  const refreshAuth = () => {
    const id = ++pollRef.current;
    fetchAniListAuth()
      .then((a) => {
        if (id !== pollRef.current) return;
        setAuth(a);
        // completed flow → sign in with the Viewer identity
        if (a.flow === "ok" && a.username) void login(a.username);
      })
      .catch(() => undefined);
  };
  useEffect(() => {
    fetchAniListAuth().then(setAuth).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (auth?.flow !== "pending") return;
    const iv = setInterval(refreshAuth, 1500);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.flow]);

  const startOauth = () => {
    startAniListLogin()
      .then(({ url }) => {
        window.open(url, "_blank", "noopener");
        setAuth((a) => (a ? { ...a, flow: "pending" } : a));
      })
      .catch(() => undefined);
  };

  // watchlist status for the open dialog (only when signed in via OAuth)
  useEffect(() => {
    if (!dialog || !auth?.authenticated) {
      setWatch(null);
      return;
    }
    setWatch(null);
    const user = result?.profile.userName ?? username;
    if (!user) return;
    let alive = true;
    watchlistStatus(user, dialog.media.id)
      .then((r) => alive && setWatch({ status: r.status, busy: false }))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialog?.media.id, auth?.authenticated]);

  // fake login persistence: a known user loads straight into their recos
  const bootRef = useRef(false);
  useEffect(() => {
    if (bootRef.current) return;
    bootRef.current = true;
    const stored = localStorage.getItem("username");
    if (stored) void run(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    localStorage.setItem("lang", lang);
    document.documentElement.lang = lang;
    // language switch recomputes recommendations and explanations: the
    // deterministic why and the LLM narrations are generated per language
    if (langRef.current !== lang) {
      langRef.current = lang;
      if (username) void run(username);
    }
  }, [lang]);

  const showView = (v: View) => {
    if (v !== "home") lastView.current = v;
    setView(v);
    localStorage.setItem("alr-view", v);
  };

  // cross-fade the incoming view + reset scroll when switching sections
  useEffect(() => {
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document
        .getElementById(`view-${view}`)
        ?.animate([{ opacity: 0.35, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], {
          duration: 220,
          easing: "ease-out",
        });
    }
    window.scrollTo({ top: 0 });
  }, [view]);

  const refreshHealth = () => {
    fetchHealth()
      .then((h) => {
        setLlmOn(h.llm.enabled);
        setLocal(h.local);
      })
      .catch(() => setLlmOn(false));
  };

  useEffect(refreshHealth, []);

  // keep the LLM chip (and the chat lock) honest: the backend may come up or
  // die at any time, the mount-time check alone froze it for the whole session
  useEffect(() => {
    const t = setInterval(refreshHealth, 60_000);
    return () => clearInterval(t);
  }, []);

  // update check: server injects APP_VERSION only when packaged
  useEffect(() => {
    fetchAppUpdate().then(setUpdate).catch(() => undefined);
  }, []);

  // manual "check now" (Settings + rail chip): fresh fetch + spinner feedback
  const [updChecking, setUpdChecking] = useState(false);
  const [updError, setUpdError] = useState(false);
  const checkUpdates = () => {
    if (updChecking) return;
    setUpdChecking(true);
    setUpdError(false);
    fetchAppUpdate(true)
      .then((u) => {
        setUpdate(u);
        if (!u.current) setUpdError(true); // dev/docker: nothing to compare against
      })
      .catch(() => setUpdError(true))
      .finally(() => setUpdChecking(false));
  };

  // the top scrim under the sticky topbar lights up once the page scrolls
  useEffect(() => {
    const el = document.getElementById("top-fade");
    const onScroll = () => el?.classList.toggle("on", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const esRef = useRef<{ close: () => void } | null>(null);

  // a stream outliving the component (or the run) would leak events — close on unmount
  useEffect(() => () => esRef.current?.close(), []);

  async function run(username: string): Promise<boolean> {
    esRef.current?.close();
    esRef.current = null;
    setUsername(username);
    setError(null);
    setResult(null);
    setWhySource({});
    setExtraRecos([]);
    setGenre("all");
    setPhase("list");
    setLoading(true);
    showView("recos");
    try {
      // fast-fail JSON (user_not_found) before opening the stream
      await fetchProfile(username);
      const stream = streamRecommend(username, lang, setPhase);
      esRef.current = stream;
      const r = await stream.done;
      esRef.current = null;
      setResult(r);
      setPhase("recos");
      return true;
      // explanations are ON-DEMAND now: fetched per-title when a detail opens
      // (DetailDialog), not for the whole list in one giant LLM prompt
    } catch (e) {
      setError(errorMessage(lang, e));
      setPhase("idle");
      return false;
    } finally {
      setLoading(false);
      esRef.current?.close();
      esRef.current = null;
      refreshHealth(); // the server may have auto-switched to local mode mid-request
    }
  }

  /** Fake login (initial or switch): persists only on success. */
  const login = async (u: string) => {
    if (await run(u)) {
      localStorage.setItem("username", u);
      setLoginOpen(false);
    }
  };

  /** Topbar anime search: any title, scored against the profile. Opening a
   *  result registers it as chat context (onOpenChat). */
  const doAnimeSearch = async () => {
    const q = animeSearch.q.trim();
    if (q.length < 2 || !username || animeSearch.busy) return;
    setAnimeSearch((s) => ({ ...s, busy: true }));
    try {
      const r = await lookupMedia(username, q, lang);
      setAnimeSearch({ q, busy: false, recos: r.recos });
    } catch {
      setAnimeSearch({ q, busy: false, recos: [] });
    }
  };

  /** DetailDialog fetched an LLM narration for one title — fold it into the result. */
  const onWhy = (id: number, text: string, source: "llm" | "cache") => {
    setWhySource((cur) => ({ ...cur, [id]: source === "cache" ? "llm" : source }));
    const fold = (list: ScoredReco[]): ScoredReco[] =>
      list.some((x) => x.media.id === id) ? list.map((x) => (x.media.id === id ? { ...x, why: text } : x)) : list;
    setResult((cur) => (cur ? { ...cur, recos: fold(cur.recos) } : cur));
    setExtraRecos((cur) => fold(cur));
  };

  /** Open from chat: looked-up titles are outside result.recos — keep them so
   *  the dialog resolves and the LLM why has somewhere to land. */
  const onOpenChat = (r: ScoredReco) => {
    if (!result?.recos.some((x) => x.media.id === r.media.id)) {
      setExtraRecos((cur) => (cur.some((x) => x.media.id === r.media.id) ? cur : [...cur, r]));
    }
    setDialog(r);
  };

  const recos = useMemo(
    () => applyFilters(result?.recos ?? [], { gemsOnly, format, genre, sort }),
    [result, gemsOnly, format, genre, sort],
  );

  const topPicks = useMemo(() => topPicksOf(result), [result]);
  const gems = useMemo(() => gemsOf(result), [result]);
  const genres = useMemo(() => topGenres(result), [result]);
  const formats = useMemo(() => formatsOf(result), [result]);

  const resetFilters = () => {
    setSort("final");
    setGemsOnly(false);
    setFormat("all");
    setGenre("all");
  };
  const filtersActive = gemsOnly || format !== "all" || genre !== "all";

  if (setup === null) {
    // status fetch in flight: minimal splash — never the full shell, or the
    // wizard decision would "flash" the app before appearing
    return (
      <main className="setup-error" aria-busy="true">
        <h1>{tr(lang, "appName")}</h1>
        <p className="loading">{tr(lang, "booting")}</p>
      </main>
    );
  }

  if (setup === "error") {
    return (
      <main className="setup-error">
        <h1>{tr(lang, "appName")}</h1>
        <p className="error">{tr(lang, "errGeneric")}</p>
        <button className="btn btn-primary" type="button" onClick={() => fetchSetupStatus().then(setSetup).catch(() => setSetup("error"))}>
          {tr(lang, "go")}
        </button>
      </main>
    );
  }

  if (setup && setup.needsSetup && !setup.customEnv) {
    return (
      <SetupWizard
        lang={lang}
        setLang={setLang}
        initial={setup}
        onDone={() => setSetup({ ...setup, needsSetup: false, setupDone: true })}
      />
    );
  }

  const hero = heroPick(topPicks);

  return (
    <>
      <div className="glow" aria-hidden="true" />
      <div className="top-fade" id="top-fade" aria-hidden="true" />
      <div className="shell" data-od-id="app-shell">
        <Rail
          view={view}
          lang={lang}
          llmOn={llmOn}
          local={local}
          onToggleLocal={() => {
            if (!local) return;
            postLocalMode(!local.auto).then((r) => setLocal(r.local)).catch(() => undefined);
          }}
          update={update}
          updateChecking={updChecking}
          onCheckUpdates={checkUpdates}
          onNav={showView}
          onLang={() => setLang(lang === "en" ? "it" : "en")}
        />

        <div className="main">
          <Topbar
            view={view}
            lang={lang}
            user={result?.profile.userName ?? username}
            busy={loading || animeSearch.busy}
            query={animeSearch.q}
            results={animeSearch.recos}
            onQuery={(q) => setAnimeSearch({ q, busy: false, recos: null })}
            onSearch={doAnimeSearch}
            onClose={() => setAnimeSearch((s) => ({ ...s, recos: null }))}
            onOpen={(r) => {
              setAnimeSearch({ q: "", busy: false, recos: null });
              onOpenChat(r);
            }}
            onSwitchUser={() => setLoginOpen(true)}
          />

          {error && (
            <div className="error-box" role="alert" data-od-id="error-box">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7.5v5.5M12 16.4v.2" />
              </svg>
              <span>{error}</span>
            </div>
          )}

          {local?.on && (
            <div className="error-box local-banner" role="status" data-od-id="local-banner">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                <path d="M12 9v4.5M12 16.6v.2" />
                <path d="M10.3 4.6 3.6 18a1.6 1.6 0 0 0 1.4 2.4h14a1.6 1.6 0 0 0 1.4-2.4L13.7 4.6a1.6 1.6 0 0 0-2.8 0z" />
              </svg>
              <span>{tr(lang, "localBanner")}</span>
              <button
                type="button"
                className="linklike"
                disabled={loading}
                onClick={() => {
                  postLocalMode(true, false)
                    .then((r) => setLocal(r.local))
                    .catch(() => undefined);
                  void run(username);
                }}
              >
                {tr(lang, "retryLive")}
              </button>
            </div>
          )}

          {/* ── HOME ── */}
          <section className="view" id="view-home" data-od-id="view-home" aria-label={tr(lang, "navHome")} hidden={view !== "home"}>
            {hero && result ? (
              <>
                <Hero reco={hero} lang={lang} user={result.profile.userName} onOpen={setDialog} onAll={() => showView("recos")} />
                <div className="sec-head">
                  <h2>{tr(lang, "sectionPicks")}</h2>
                  <button className="more" type="button" onClick={() => showView("recos")}>{tr(lang, "seeAll")}</button>
                </div>
                <Carousel label={tr(lang, "sectionPicks")} prev={tr(lang, "carPrev")} next={tr(lang, "carNext")}>
                  {carouselPicks(topPicks).map((r) => (
                    <MediaCard key={r.media.id} reco={r} lang={lang} eager onOpen={setDialog} />
                  ))}
                </Carousel>
                {genres.length > 0 && (
                  <div className="genre-row" data-od-id="genre-row">
                    {genres.map((g) => (
                      <button
                        key={g}
                        type="button"
                        className="genre-chip"
                        aria-pressed={genre === g}
                        onClick={() => {
                          setGenre(genre === g ? "all" : g);
                          showView("recos");
                        }}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                )}
                <div className="stats" data-od-id="stats-row">
                  <div className="stat"><div className="num">{result.profile.meanScore}</div><div className="lbl">{tr(lang, "statMean", { n: result.profile.scoredCount })}</div></div>
                  <div className="stat"><div className="num">{result.profile.counts.COMPLETED}</div><div className="lbl">{tr(lang, "statDone")}</div></div>
                  <div className="stat"><div className="num">{gems.length}</div><div className="lbl">{tr(lang, "statGems")}</div></div>
                  <div className="stat"><div className="num">{score110(hero.final)}<small>/110</small></div><div className="lbl">{tr(lang, "statTop")}</div></div>
                </div>
              </>
            ) : (
              <div className="state-box welcome" data-od-id="home-empty">
                <svg className="mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M4.4 8Q12 5.4 19.6 8" />
                  <path d="M12 6.6V9.6" />
                  <path d="M6.3 9.6h11.4" />
                  <path d="M7.7 9.6V19M16.3 9.6V19" />
                  <path d="M5.9 14.2h12.2" />
                </svg>
                <p className="big">{tr(lang, "appName")}</p>
                <p>{tr(lang, "tagline")}</p>
                <p className="hint">{tr(lang, "welcomeHint")}</p>
              </div>
            )}
          </section>

          {/* ── CONSIGLI ── */}
          <section className="view" id="view-recos" data-od-id="view-recos" aria-label={tr(lang, "navRecos")} hidden={view !== "recos"}>
            {loading && !result ? (
              <div className="skeleton" aria-hidden="true">
                {Array.from({ length: 10 }, (_, i) => (
                  <div className="sk" key={i}>
                    <div className="ph" />
                    <div className="ln" />
                    <div className="ln s" />
                  </div>
                ))}
              </div>
            ) : phase !== "idle" && phase !== "recos" ? (
              <Progress lang={lang} phase={phase} />
            ) : (
              result && (
                <>
                  <div className="toolbar" data-od-id="toolbar-recos">
                    <div className="seg" role="group" aria-label={tr(lang, "sortFinal")}>
                      {(["final", "gem", "affinity"] as SortKey[]).map((k) => (
                        <button key={k} type="button" aria-pressed={sort === k} onClick={() => setSort(k)}>
                          {tr(lang, k === "final" ? "sortFinal" : k === "gem" ? "sortGem" : "sortAffinity")}
                        </button>
                      ))}
                    </div>
                    <div className="seg" role="group" aria-label={tr(lang, "fmtAll")}>
                      <button type="button" aria-pressed={format === "all"} onClick={() => setFormat("all")}>{tr(lang, "fmtAll")}</button>
                      {formats.map((f) => (
                        <button key={f} type="button" aria-pressed={format === f} onClick={() => setFormat(f)}>
                          {f === "MOVIE" ? tr(lang, "fmtMovie") : f}
                        </button>
                      ))}
                    </div>
                    <div className="seg" role="group" aria-label={tr(lang, "gemsOnly")}>
                      <button type="button" aria-pressed={!gemsOnly} onClick={() => setGemsOnly(false)}>{tr(lang, "gemsOff")}</button>
                      <button type="button" aria-pressed={gemsOnly} onClick={() => setGemsOnly(true)}>{tr(lang, "gemsOnly")}</button>
                    </div>
                    {genre !== "all" && (
                      <button type="button" className="genre-chip" aria-pressed="true" onClick={() => setGenre("all")}>
                        {tr(lang, "genreFilterOn", { g: genre })}
                      </button>
                    )}
                    <span className="spacer" />
                    <span className="count-lbl mono">{tr(lang, "resultsLbl", { n: recos.length })}</span>
                  </div>

                  {recos.length > 0 ? (
                    <div className="grid" data-od-id="recos-grid">
                      {recos.map((r, i) => (
                        <MediaCard key={r.media.id} reco={r} lang={lang} eager={i < 6} onOpen={setDialog} />
                      ))}
                    </div>
                  ) : (
                    <div className="state-box" data-od-id="recos-empty">
                      <p className="big">{tr(lang, "emptyBig")}</p>
                      <p>{tr(lang, "emptySub")}</p>
                      {filtersActive && (
                        <button className="more" type="button" onClick={resetFilters}>{tr(lang, "resetFilters")}</button>
                      )}
                    </div>
                  )}
                </>
              )
            )}
          </section>

          {/* ── GEMME ── */}
          <section className="view" id="view-gems" data-od-id="view-gems" aria-label={tr(lang, "navGems")} hidden={view !== "gems"}>
            <div className="sec-head" style={{ marginTop: 0 }}>
              <div>
                <h2>{tr(lang, "gemsTitle")}</h2>
                <p>{tr(lang, "gemsSub")}</p>
              </div>
            </div>
            {gems.length > 0 ? (
              <div className="grid" data-od-id="gems-grid">
                {gems.map((r, i) => (
                  <MediaCard key={r.media.id} reco={r} lang={lang} eager={i < 6} onOpen={setDialog} />
                ))}
              </div>
            ) : (
              <div className="state-box"><p>{loading ? tr(lang, "loadingRecos") : tr(lang, "emptyState")}</p></div>
            )}
          </section>

          {/* ── CHAT ── */}
          <section className="view" id="view-chat" data-od-id="view-chat" aria-label={tr(lang, "chatTitle")} hidden={view !== "chat"}>
            <div className="sec-head" style={{ marginTop: 0 }}>
              <div>
                <h2>{tr(lang, "chatTitle")}</h2>
                <p>{tr(lang, "chatSub")}</p>
              </div>
            </div>
            <ChatPanel
              lang={lang}
              result={result}
              llmOn={llmOn}
              username={result?.profile.userName ?? username}
              extras={extraRecos}
              onOpen={onOpenChat}
            />
          </section>

          {/* ── PROFILO ── */}
          <section className="view" id="view-profile" data-od-id="view-profile" aria-label={tr(lang, "navProfile")} hidden={view !== "profile"}>
            {result ? (
              <>
                <div className="sec-head" style={{ marginTop: 0 }}>
                  <div>
                    <h2>{tr(lang, "profTitle")}</h2>
                    <p>{tr(lang, "profSub")}</p>
                  </div>
                  <span className={`conf${result.profile.confidence === "low" ? " low" : ""}`}>
                    <span className="dot" aria-hidden="true" />
                    {tr(lang, result.profile.confidence === "ok" ? "confOk" : "confidenceLow")}
                  </span>
                </div>
                <ProfileView profile={result.profile} lang={lang} />
              </>
            ) : (
              <div className="state-box"><p>{tr(lang, "emptyState")}</p></div>
            )}
          </section>

          {/* ── EVITA ── */}
          <section className="view" id="view-avoid" data-od-id="view-avoid" aria-label={tr(lang, "navAvoid")} hidden={view !== "avoid"}>
            <div className="sec-head" style={{ marginTop: 0 }}>
              <div>
                <h2>{tr(lang, "avoidTitle")}</h2>
                <p>{tr(lang, "avoidSub")}</p>
              </div>
            </div>
            {result && result.avoided.length > 0 ? (
              <AvoidList items={result.avoided} lang={lang} />
            ) : (
              <div className="state-box"><p>{tr(lang, "emptyState")}</p></div>
            )}
          </section>

          {/* ── IMPOSTAZIONI ── */}
          <section className="view" id="view-settings" data-od-id="view-settings" aria-label={tr(lang, "navSettings")} hidden={view !== "settings"}>
            <div className="sec-head" style={{ marginTop: 0 }}>
              <div>
                <h2>{tr(lang, "navSettings")}</h2>
              </div>
            </div>

            <div className="set-row">
              <span>{tr(lang, "setTitleLang")}</span>
              <div className="seg" role="group" aria-label={tr(lang, "setTitleLang")}>
                <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
                <button type="button" aria-pressed={lang === "it"} onClick={() => setLang("it")}>IT</button>
              </div>
            </div>

            {local?.available && (
              <div className="set-row">
                <span>{tr(lang, "setTitleData")}</span>
                <button
                  type="button"
                  className="linklike"
                  role="switch"
                  aria-checked={local.auto}
                  onClick={() => {
                    postLocalMode(!local.auto).then((r) => setLocal(r.local)).catch(() => undefined);
                  }}
                >
                  {tr(lang, "localAuto")} — {local.auto ? tr(lang, "on") : tr(lang, "off")}
                </button>
              </div>
            )}

            <div className="set-row">
              <span>{tr(lang, "setTitleUpd")}</span>
              <div className="set-stack">
                {update?.available && !updChecking ? (
                  <button type="button" className="linklike" onClick={() => update.url && window.open(update.url, "_blank", "noopener")}>
                    {tr(lang, "updateAvailable", { v: update.latest ?? "" })}
                  </button>
                ) : (
                  <button type="button" className="linklike set-check" disabled={updChecking} onClick={checkUpdates}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" className={updChecking ? "spin" : undefined}>
                      <path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4" />
                    </svg>
                    {updChecking ? tr(lang, "checking") : tr(lang, "checkUpdates")}
                  </button>
                )}
                {updError && <small className="err">{tr(lang, "errGeneric")}</small>}
                {!updError && update?.latest && !update.available && <small>{tr(lang, "upToDate")}</small>}
                {update?.current && <small>{tr(lang, "currentVersion", { v: update.current })}</small>}
              </div>
            </div>

            <div className="set-row">
              <span>{tr(lang, "setTitleLlm")}</span>
              <div className="set-stack">
                <small className={llmOn ? "ok" : undefined}>{llmOn ? tr(lang, "llmOn") : tr(lang, "llmOff")}</small>
                <button
                  type="button"
                  className="linklike"
                  onClick={() => {
                    // reopen the wizard in place: no full page reload (it rebooted
                    // every probe and took seconds) — the status fetch gates the render
                    postSetup("reset")
                      .then(() => fetchSetupStatus())
                      .then((s) => setSetup(s))
                      .catch(() => setSetup("error"));
                  }}
                >
                  {tr(lang, "rerunSetup")}
                </button>
              </div>
            </div>

            <LlmSettings lang={lang} onSaved={refreshHealth} />

            <AniListAuthPanel lang={lang} onAuthChange={setAuth} />
          </section>

          <footer className="pagefoot" data-od-id="footer">
            <span>{tr(lang, "apiHint")}</span>
            <span className="mono">anilist.co</span>
          </footer>
        </div>
      </div>

      {loginOpen && (
        <LoginModal
          lang={lang}
          busy={loading}
          error={error}
          current={username || undefined}
          oauthConfigured={auth?.configured}
          oauthPending={auth?.flow === "pending"}
          onOauth={startOauth}
          onLogin={login}
        />
      )}

      {dialog && (
        <DetailDialog
          reco={
            result?.recos.find((x) => x.media.id === dialog.media.id) ??
            extraRecos.find((x) => x.media.id === dialog.media.id) ??
            dialog
          }
          lang={lang}
          username={result?.profile.userName ?? username}
          whySource={whySource[dialog.media.id] ?? "local"}
          onWhy={onWhy}
          onClose={() => setDialog(null)}
          onSimilar={() => {
            setDialog(null);
            setSort("affinity");
            showView(lastView.current);
          }}
          watchStatus={auth?.authenticated ? (watch?.status ?? null) : undefined}
          watchBusy={watch?.busy}
          onAddToWatchlist={
            auth?.authenticated && dialog
              ? () => {
                  setWatch({ status: watch?.status ?? null, busy: true });
                  addToWatchlist(dialog.media.id)
                    .then((r) => setWatch({ status: r.status, busy: false }))
                    .catch((e) => {
                      setWatch({ status: null, busy: false });
                      setError(errorMessage(lang, e));
                    });
                }
              : undefined
          }
        />
      )}
    </>
  );
}
