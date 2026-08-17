import type { Metadata } from "next";
import { FamilyConsole } from "./_components/FamilyConsole";

export const metadata: Metadata = {
  title: "Familieportalen",
  description: "Familiens felles skjerm for uke, gjøremål og FamilyBot-drift.",
};

export default function Home() {
  return <FamilyConsole />;
}
