import { tr, type Lang } from "../i18n.ts";

/** Server error code → user message: user_not_found / anilist_error /
 *  anilist_auth / generic. */
export const errorMessage = (lang: Lang, e: unknown): string =>
  e instanceof Error && e.message === "user_not_found"
    ? tr(lang, "errUserNotFound")
    : e instanceof Error && e.message === "anilist_error"
      ? tr(lang, "errAnilistDown")
      : e instanceof Error && e.message === "anilist_auth"
        ? tr(lang, "errAnilistAuth")
        : tr(lang, "errGeneric");
