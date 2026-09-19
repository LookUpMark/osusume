export type View = "home" | "recos" | "gems" | "chat" | "profile" | "avoid" | "settings";

/** i18n key of the section title, reused for page title + rail tooltips. */
export const VIEW_LABEL: Record<View, string> = {
  home: "navHome",
  recos: "navRecos",
  gems: "navGems",
  chat: "chatTitle",
  profile: "navProfile",
  avoid: "navAvoid",
  settings: "navSettings",
};
