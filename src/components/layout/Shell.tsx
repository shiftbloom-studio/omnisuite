import type { ReactNode } from "react";
import Sidebar from "./Sidebar";
import Titlebar from "./Titlebar";

interface ShellProps {
  children: ReactNode;
}

function Shell({ children }: ShellProps) {
  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#0A0A0A]">
      <Titlebar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}

export default Shell;
