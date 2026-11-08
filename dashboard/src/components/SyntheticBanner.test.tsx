import { render, screen } from "@testing-library/react";
import { SyntheticBanner } from "./SyntheticBanner";
import { SYNTHETIC_DISCLAIMER } from "../copy";

describe("SyntheticBanner", () => {
  it("labels demo data so the numbers cannot be mistaken for a live trace", () => {
    render(<SyntheticBanner disclaimer={SYNTHETIC_DISCLAIMER} />);
    expect(screen.getByRole("status").textContent).toContain("Synthetic demo data");
    expect(screen.getByRole("status").textContent).toContain("Not a live provider trace");
  });
});
