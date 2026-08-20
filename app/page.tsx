import type { Metadata } from "next";
import { FamilyConsole } from "./_components/FamilyConsole";

export const metadata: Metadata = {
  title: "Familieportalen",
  description: "A shared family dashboard for schedules, chores, rewards, and FamilyBot status.",
};

export default function Home() {
  return <FamilyConsole />;
}
