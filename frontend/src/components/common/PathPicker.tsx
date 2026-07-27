import { useEffect, useState } from "react";
import { ApiError, getFsList, getFsRoots } from "../../api/client";
import type { FsEntry, FsListing, FsRoot } from "../../api/types";
import { useI18n } from "../../i18n";
import { BlueprintCard } from "./BlueprintCard";
import { Btn } from "./Btn";
import { Chip } from "./Chip";
import "./PathPicker.css";
import { pp } from "./PathPicker.strings";

export type PathPickerMode = "directory" | "project";

interface PathPickerProps {
  mode: PathPickerMode;
  title: string;
  initialPath?: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

/** api-contract.md §ファイル選択 (Welcome のファイル選択ウィンドウ) — an
 * in-app file selection window (backdrop + dialog, mirrors SettingsModal's
 * structure) backed by GET /api/fs/roots + GET /api/fs/list, since a browser
 * <input type=file> cannot hand back a real filesystem path.
 *
 * mode="directory": the currently *browsed* directory is always selectable
 * (SELECT returns the directory being listed — there is nothing further to
 * pick inside it).
 * mode="project": SELECT is only enabled once the target is either a
 * directory flagged `is_project` (a project.json lives directly inside it)
 * or an explicitly clicked `.json` file — anything else is disabled with an
 * inline reason (api-contract.md: "それ以外の SELECT は disabled + 理由表示"). */
export function PathPicker({ mode, title, initialPath, onSelect, onClose }: PathPickerProps) {
  const { lang } = useI18n();
  const t = (key: Parameters<typeof pp>[1]) => pp(lang, key);

  const [roots, setRoots] = useState<FsRoot[]>([]);
  const [listing, setListing] = useState<FsListing | null>(null);
  // Whether the directory currently being browsed (`listing.path`) is itself
  // a project directory — known only when we descended into it via an entry
  // row that carried `is_project` (roots and "up to parent" navigation don't
  // carry that flag for the destination, so they reset it to false; a
  // judgment call documented here rather than silently guessed).
  const [currentIsProject, setCurrentIsProject] = useState(false);
  // mode="project" only: an explicitly clicked `.json` file within the
  // current listing. Cleared on every navigation.
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function navigate(path: string, isProject: boolean) {
    setLoading(true);
    setError(null);
    try {
      const res = await getFsList(path);
      setListing(res);
      setCurrentIsProject(isProject);
      setSelectedFile(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("picker.error.generic"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    getFsRoots()
      .then((res) => {
        if (cancelled) return;
        setRoots(res.roots);
        const start = initialPath?.trim() || res.roots[0]?.path;
        if (start) navigate(start, false);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("picker.error.generic"));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  function handleEntryClick(entry: FsEntry) {
    if (entry.is_dir) {
      navigate(entry.path, entry.is_project);
    } else if (mode === "project") {
      // Only reachable in mode="project" — mode="directory" file rows are
      // rendered non-interactive below (there is nothing to select inside a
      // directory-only picker).
      setSelectedFile(entry.path);
    }
  }

  const currentPath = selectedFile ?? listing?.path ?? "";
  const canSelect =
    mode === "directory" ? listing !== null : selectedFile !== null || currentIsProject;

  function handleSelect() {
    if (!canSelect) return;
    onSelect(currentPath);
  }

  return (
    <div className="path-picker__backdrop" onClick={onClose} role="presentation">
      <div
        className="path-picker__dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <BlueprintCard heading={title} className="path-picker__card">
          <div className="path-picker__body">
            <div className="path-picker__panes">
              <div className="path-picker__roots">
                <div className="path-picker__roots-heading">{t("picker.roots.heading")}</div>
                {roots.map((root) => (
                  <button
                    type="button"
                    key={root.path}
                    className="path-picker__root-row"
                    disabled={loading}
                    onClick={() => navigate(root.path, false)}
                  >
                    {root.label}
                  </button>
                ))}
              </div>

              <div className="path-picker__main">
                <div className="path-picker__breadcrumb">
                  <button
                    type="button"
                    className="path-picker__up-btn"
                    aria-label={t("picker.up.label")}
                    title={t("picker.up.label")}
                    disabled={loading || !listing?.parent}
                    onClick={() => listing?.parent && navigate(listing.parent, false)}
                  >
                    ‹
                  </button>
                  <span className="path-picker__breadcrumb-path">{listing?.path ?? ""}</span>
                </div>

                <div className="path-picker__entries" role="listbox">
                  {loading && <div className="path-picker__note">{t("picker.loading")}</div>}
                  {!loading && listing && listing.entries.length === 0 && (
                    <div className="path-picker__note">{t("picker.entries.empty")}</div>
                  )}
                  {!loading &&
                    listing?.entries.map((entry) => {
                      const interactive = entry.is_dir || mode === "project";
                      const selected = !entry.is_dir && selectedFile === entry.path;
                      return (
                        <button
                          type="button"
                          key={entry.path}
                          role="option"
                          aria-selected={selected}
                          className={`path-picker__entry${entry.is_dir ? " path-picker__entry--dir" : ""}${selected ? " path-picker__entry--selected" : ""}`}
                          disabled={!interactive}
                          onClick={() => handleEntryClick(entry)}
                        >
                          <span className="path-picker__entry-icon">{entry.is_dir ? "›" : "·"}</span>
                          <span className="path-picker__entry-name">{entry.name}</span>
                          {entry.is_project && (
                            <Chip variant="accent" className="path-picker__entry-chip">
                              {t("picker.entries.projectChip")}
                            </Chip>
                          )}
                        </button>
                      );
                    })}
                </div>
              </div>
            </div>

            {error && <div className="path-picker__message path-picker__message--error">{error}</div>}

            <div className="path-picker__footer">
              <div className="path-picker__current">
                <span className="path-picker__current-label">{t("picker.currentPath.label")}</span>
                <span className="path-picker__current-path">{currentPath}</span>
              </div>
              {!canSelect && mode === "project" && (
                <div className="path-picker__reason">{t("picker.reason.project")}</div>
              )}
              <div className="path-picker__actions">
                <Btn type="button" variant="accent" disabled={!canSelect} onClick={handleSelect}>
                  {t("picker.select")}
                </Btn>
                <Btn type="button" variant="outline" onClick={onClose}>
                  {t("picker.cancel")}
                </Btn>
              </div>
            </div>
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}
