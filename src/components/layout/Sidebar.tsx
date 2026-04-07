import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/", label: "SYNTHESIZE" },
  { to: "/clone", label: "CLONE" },
  { to: "/library", label: "VOICES" },
  { to: "/design", label: "DESIGN" },
  { to: "/settings", label: "SETTINGS" },
];

function Sidebar() {
  return (
    <aside className="w-[180px] min-w-[180px] h-full bg-[#141414] border-r-[3px] border-r-[#1a1a1a] flex flex-col justify-between select-none">
      <div>
        {/* Branding */}
        <div className="flex items-center gap-2 px-5 pt-6 pb-8">
          <div className="w-3 h-3 bg-[#FF3D00]" />
          <span className="text-[13px] font-black tracking-[3px]">
            <span className="text-[#FF3D00]">OMNI</span>
            <span className="text-[#888]">SUITE</span>
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex flex-col gap-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `block px-5 py-2.5 text-[11px] font-bold tracking-[3px] uppercase transition-colors border-l-4 ${
                  isActive
                    ? "border-l-[#FF3D00] text-[#E0E0E0] bg-[#1a1a1a]"
                    : "border-l-transparent text-[#888] hover:text-[#E0E0E0] hover:bg-[#1a1a1a]/50"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Active Voice */}
      <div className="px-5 pb-6">
        <div className="text-[9px] font-bold tracking-[3px] text-[#888] uppercase mb-1.5">
          ACTIVE VOICE
        </div>
        <div className="text-[11px] font-bold text-[#E0E0E0] tracking-[1px]">
          None selected
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
