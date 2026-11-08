import { bannerTone } from "@/lib/regression";

export function SyntheticBanner({ disclaimer }: { disclaimer: string }) {
  const tone = bannerTone(disclaimer);
  if (tone === "none") return null;
  const mixed = tone === "mixed";
  return (
    <div
      role="status"
      className={
        mixed
          ? "border-b border-[#e4c56a] bg-[#fff4d6] px-4 py-3 text-[#6a4a00] md:px-8"
          : "border-b border-[#c9b48a] bg-[#f6edd8] px-4 py-3 text-[#5c4a32] md:px-8"
      }
    >
      <p className="nums text-[11px] tracking-[0.16em] uppercase">
        {mixed ? "Mixed ledger" : "Synthetic demo data"}
      </p>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed">{disclaimer}</p>
    </div>
  );
}
