import { useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  getRecentProjects,
  postProjectCreate,
  postProjectDemo,
  postProjectOpen,
} from "../../api/client";
import type { RecentProject } from "../../api/types";
import { useI18n } from "../../i18n";
import { BlueprintCard, Btn, PathPicker } from "../common";
import "./WelcomeScreen.css";
import { wt } from "./WelcomeScreen.strings";

type Busy = "create" | "open" | "sample" | null;

// Which BROWSE… button opened the picker — drives PathPicker's mode and
// which input field the selected path is written back into
// (api-contract.md §ファイル選択: NEW PROJECT gets a directory picker, OPEN
// gets a project picker). null = picker closed.
type PickerTarget = "directory" | "openPath" | null;

interface WelcomeScreenProps {
  /** Called after project create/open/demo succeeds. The caller (App.tsx)
   * re-fetches GET /api/state + /api/viewmodel, which flips
   * state.shell.source away from "none" and swaps this screen out for the
   * normal 3-pane workbench — this component does not touch global state
   * itself. */
  onReady: () => void;
}

/** REQ-GUI-017 — shown instead of the 3-pane workbench body while
 * state.shell.source === "none" (no project loaded). Three lanes: create a
 * new project (name + directory), open an existing one (path, or a RECENT
 * pick), or browse the read-only sample (demo mode). */
export function WelcomeScreen({ onReady }: WelcomeScreenProps) {
  const { lang } = useI18n();
  const t = (key: Parameters<typeof wt>[1]) => wt(lang, key);

  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [openPath, setOpenPath] = useState("");
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickerTarget, setPickerTarget] = useState<PickerTarget>(null);

  useEffect(() => {
    let cancelled = false;
    getRecentProjects()
      .then((res) => {
        if (!cancelled) setRecent(res.projects);
      })
      .catch(() => {
        // RECENT is best-effort UI sugar — a failed fetch just leaves the
        // list empty, it must not block CREATE/OPEN/SAMPLE.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function reportError(err: unknown) {
    setError(err instanceof ApiError ? err.message : t("welcome.error.generic"));
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !directory.trim() || busy) return;
    setError(null);
    setBusy("create");
    try {
      await postProjectCreate({ name: name.trim(), directory: directory.trim() });
      onReady();
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(null);
    }
  }

  async function handleOpen(path: string) {
    if (!path.trim() || busy) return;
    setError(null);
    setBusy("open");
    try {
      await postProjectOpen({ path: path.trim() });
      onReady();
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(null);
    }
  }

  function handlePickerSelect(path: string) {
    if (pickerTarget === "directory") setDirectory(path);
    else if (pickerTarget === "openPath") setOpenPath(path);
    setPickerTarget(null);
  }

  async function handleSample() {
    if (busy) return;
    setError(null);
    setBusy("sample");
    try {
      await postProjectDemo();
      onReady();
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="welcome-screen">
      <div className="welcome-screen__intro">
        <span className="welcome-screen__title">{t("welcome.title")}</span>
        <span className="welcome-screen__subtitle">{t("welcome.subtitle")}</span>
      </div>

      {error && <div className="welcome-screen__error">{error}</div>}

      <div className="welcome-screen__grid">
        <BlueprintCard heading={t("welcome.new.heading")} className="welcome-card">
          <form className="welcome-form" onSubmit={handleCreate}>
            <label className="welcome-form__field">
              <span>{t("welcome.new.nameLabel")}</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("welcome.new.namePlaceholder")}
                aria-label={t("welcome.new.nameLabel")}
              />
            </label>
            <label className="welcome-form__field">
              <span>{t("welcome.new.directoryLabel")}</span>
              <div className="welcome-form__field-row">
                <input
                  value={directory}
                  onChange={(e) => setDirectory(e.target.value)}
                  placeholder={t("welcome.new.directoryPlaceholder")}
                  aria-label={t("welcome.new.directoryLabel")}
                />
                <Btn type="button" variant="outline" onClick={() => setPickerTarget("directory")}>
                  {t("welcome.browse")}
                </Btn>
              </div>
            </label>
            <Btn
              type="submit"
              variant="accent"
              disabled={busy === "create" || !name.trim() || !directory.trim()}
            >
              {busy === "create" ? t("welcome.new.creating") : t("welcome.new.create")}
            </Btn>
          </form>
        </BlueprintCard>

        <BlueprintCard heading={t("welcome.open.heading")} className="welcome-card">
          <div className="welcome-form">
            <label className="welcome-form__field">
              <span>{t("welcome.open.pathLabel")}</span>
              <div className="welcome-form__field-row">
                <input
                  value={openPath}
                  onChange={(e) => setOpenPath(e.target.value)}
                  placeholder={t("welcome.open.pathPlaceholder")}
                  aria-label={t("welcome.open.pathLabel")}
                />
                <Btn type="button" variant="outline" onClick={() => setPickerTarget("openPath")}>
                  {t("welcome.browse")}
                </Btn>
              </div>
            </label>
            <Btn
              type="button"
              variant="accent"
              disabled={busy === "open" || !openPath.trim()}
              onClick={() => handleOpen(openPath)}
            >
              {busy === "open" ? t("welcome.open.opening") : t("welcome.open.open")}
            </Btn>
            <div className="welcome-recent">
              <span className="welcome-recent__heading">{t("welcome.open.recentHeading")}</span>
              {recent.length === 0 && (
                <span className="welcome-recent__empty">{t("welcome.open.recentEmpty")}</span>
              )}
              {recent.map((p) => (
                <button
                  type="button"
                  key={p.path}
                  className="welcome-recent__row"
                  disabled={busy !== null}
                  onClick={() => handleOpen(p.path)}
                >
                  <span className="welcome-recent__name">{p.name}</span>
                  <span className="welcome-recent__path">{p.path}</span>
                  <span className="welcome-recent__time">{p.last_opened}</span>
                </button>
              ))}
            </div>
          </div>
        </BlueprintCard>

        <BlueprintCard heading={t("welcome.sample.heading")} className="welcome-card">
          <div className="welcome-form">
            <p className="welcome-sample__note">{t("welcome.sample.note")}</p>
            <Btn type="button" variant="outline" disabled={busy === "sample"} onClick={handleSample}>
              {busy === "sample" ? t("welcome.sample.opening") : t("welcome.sample.open")}
            </Btn>
          </div>
        </BlueprintCard>
      </div>

      {pickerTarget && (
        <PathPicker
          mode={pickerTarget === "directory" ? "directory" : "project"}
          title={pickerTarget === "directory" ? t("welcome.new.directoryLabel") : t("welcome.open.pathLabel")}
          initialPath={pickerTarget === "directory" ? directory : openPath}
          onSelect={handlePickerSelect}
          onClose={() => setPickerTarget(null)}
        />
      )}
    </div>
  );
}
