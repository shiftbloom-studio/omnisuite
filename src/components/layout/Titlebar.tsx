import { getCurrentWindow } from "@tauri-apps/api/window";

function Titlebar() {
  const appWindow = getCurrentWindow();

  return (
    <div className="bg-[#0F0F0F] border-t-[3px] border-t-[#FF3D00] select-none">
      <div
        data-tauri-drag-region
        className="flex items-center justify-between h-8 px-4"
      >
        <span className="text-[9px] font-bold tracking-[4px] text-[#888] uppercase pointer-events-none">
          OMNISUITE
        </span>

        <div className="flex items-center gap-0">
          <button
            onClick={() => appWindow.minimize()}
            className="w-8 h-8 flex items-center justify-center text-[#888] hover:text-[#E0E0E0] hover:bg-[#1a1a1a] transition-colors"
            aria-label="Minimize"
          >
            <svg width="10" height="1" viewBox="0 0 10 1" fill="currentColor">
              <rect width="10" height="1" />
            </svg>
          </button>
          <button
            onClick={() => appWindow.toggleMaximize()}
            className="w-8 h-8 flex items-center justify-center text-[#888] hover:text-[#E0E0E0] hover:bg-[#1a1a1a] transition-colors"
            aria-label="Maximize"
          >
            <svg
              width="9"
              height="9"
              viewBox="0 0 9 9"
              fill="none"
              stroke="currentColor"
              strokeWidth="1"
            >
              <rect x="0.5" y="0.5" width="8" height="8" />
            </svg>
          </button>
          <button
            onClick={() => appWindow.close()}
            className="w-8 h-8 flex items-center justify-center text-[#888] hover:text-[#FF3D00] hover:bg-[#1a1a1a] transition-colors"
            aria-label="Close"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
            >
              <line x1="1" y1="1" x2="9" y2="9" />
              <line x1="9" y1="1" x2="1" y2="9" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default Titlebar;
