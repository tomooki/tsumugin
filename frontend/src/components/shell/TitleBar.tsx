import type { GuiMode } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { Chip } from "../common";
import "./shell.css";

interface TitleBarProps {
  onModeChange: (mode: GuiMode) => void;
}

/** 56px title bar: TSUMUGIN logo + version/GSAS-II chips, centred mode
 * toggle, EN/日本語 segment + status chips. Handoff README §1. */
export function TitleBar({ onModeChange }: TitleBarProps) {
  const { state, dispatch } = useStore();
  const { t } = useI18n();
  const idle = state.shell?.agent.idle ?? state.mode === "manual";

  const modes: { key: GuiMode; labelKey: "mode.manual.label" | "mode.auto.label"; subKey: "mode.manual.sub" | "mode.auto.sub" }[] = [
    { key: "manual", labelKey: "mode.manual.label", subKey: "mode.manual.sub" },
    { key: "auto", labelKey: "mode.auto.label", subKey: "mode.auto.sub" },
  ];

  return (
    <div className="title-bar">
      <div className="title-bar__brand">
        <span className="title-bar__logo">TSUMUGIN</span>
        <span className="title-bar__version">v0.3 · M0–M11</span>
        <Chip variant="accent">{t("shell.gsasChip")}</Chip>
      </div>

      <div className="title-bar__mode-wrap">
        <div className="mode-toggle blueprint">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {modes.map((m) => {
            const active = state.mode === m.key;
            return (
              <button
                key={m.key}
                type="button"
                className={`mode-toggle__btn${active ? " mode-toggle__btn--active" : ""}`}
                onClick={() => onModeChange(m.key)}
              >
                <span className="mode-toggle__dot" />
                <span>
                  <span className="mode-toggle__label">{t(m.labelKey)}</span>
                  <span className="mode-toggle__sub">{t(m.subKey)}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="title-bar__right">
        <div className="lang-seg">
          <button
            type="button"
            className={`lang-seg__btn${state.lang === "en" ? " lang-seg__btn--active" : ""}`}
            onClick={() => dispatch({ type: "SET_LANG", lang: "en" })}
          >
            EN
          </button>
          <button
            type="button"
            className={`lang-seg__btn${state.lang === "ja" ? " lang-seg__btn--active" : ""}`}
            onClick={() => dispatch({ type: "SET_LANG", lang: "ja" })}
          >
            日本語
          </button>
        </div>
        <Chip>
          <span className="title-bar__dot" />
          {t("shell.nonDestructive")}
        </Chip>
        <Chip>ledger.verify() = TRUE</Chip>
        <Chip>{idle ? t("status.cost.idle") : t("status.cost.active")}</Chip>
      </div>
    </div>
  );
}
