import { weekPlanBlocks } from "./weekPlanText";

export type WeekPlanInterpretationItem = {
  category: "homework" | "bring" | "event" | "subject" | "notice" | "general";
  text: string;
  source_blocks: string[];
  confidence: number;
};
export type WeekPlanInterpretation = {
  version: number; week: number; year: number;
  days: Array<{ date: string; weekday: string; items: WeekPlanInterpretationItem[] }>;
  weekly_tasks?: Array<{ text: string; source_blocks: string[] }>;
  general_info?: Array<{ text: string; source_blocks: string[] }>;
  general_notes?: Array<{ text: string; source_blocks: string[] }>;
};

export function WeekPlanText({ text, headingLevel = 3, inList = false }: { text: string; headingLevel?: 3 | 4 | 5; inList?: boolean }) {
  const blocks = weekPlanBlocks(text);
  const Heading = headingLevel === 5 ? "h5" : headingLevel === 4 ? "h4" : "h3";
  return <div className="week-plan-rich-text" aria-label="Strukturert ukeplan">
    {blocks.map((block, index) => {
      if (block.kind === "heading") return <Heading className="week-plan-heading" key={index}>{block.text}</Heading>;
      if (block.kind === "paragraph") return <p key={index}>{block.text}</p>;
      const List = block.ordered ? "ol" : "ul";
      // One nested formatting pass is enough for labels inside bullets. Bound it
      // so adversarial repeated bullet prefixes cannot cause recursive rendering.
      return <List className="week-plan-list" start={block.start} key={index}>{block.items.map((item, i) => <li key={i}>{inList?item:<WeekPlanText text={item} headingLevel={headingLevel} inList/>}</li>)}</List>;
    })}
    {!blocks.length && <p className="empty-text">Ingen plantekst er tilgjengelig.</p>}
  </div>;
}

const labels: Record<WeekPlanInterpretationItem["category"], string> = {
  homework: "Lekser", bring: "Ta med / husk", event: "Dette skjer",
  subject: "Fag og læringsmål", notice: "Beskjeder", general: "Informasjon",
};

export function WeekPlanInterpreted({ interpretation }: { interpretation: WeekPlanInterpretation }) {
  const days = interpretation.days.filter(day => day.items.length > 0);
  const weeklyTasks = interpretation.weekly_tasks || [];
  const generalInfo = interpretation.general_info?.length ? interpretation.general_info : interpretation.general_notes || [];
  return <div className="week-plan-interpretation" aria-label="Tolkede ukeplanpunkter">
    {days.map(day => {
      // Group consecutive categories only: never reorder instructions within a day.
      const groups: Array<{ category: WeekPlanInterpretationItem["category"]; items: WeekPlanInterpretationItem[] }> = [];
      for (const item of day.items) {
        const last = groups.at(-1);
        if (last?.category === item.category) last.items.push(item);
        else groups.push({ category: item.category, items: [item] });
      }
      return <section className="week-plan-interpretation-day" key={day.date}>
        <h3>{day.weekday}</h3>
        {groups.map((group, index) => <section className="week-plan-category" key={index}>
          <h4>{labels[group.category]}</h4>
          {group.items.map((item, i) => <WeekPlanText text={item.text} headingLevel={5} key={i} />)}
        </section>)}
      </section>;
    })}
    {weeklyTasks.length > 0 && <section className="week-plan-weekly-tasks"><h3>Dette må gjøres denne uken</h3>
      {weeklyTasks.map((note, index) => <WeekPlanText text={note.text} headingLevel={4} key={index} />)}
    </section>}
    {generalInfo.length > 0 && <section className="week-plan-general-info"><h3>Generell informasjon</h3>
      {generalInfo.map((note, index) => <WeekPlanText text={note.text} headingLevel={4} key={index} />)}
    </section>}
    {!days.length && !weeklyTasks.length && !generalInfo.length && <p className="empty-text">Ingen strukturerte punkter er tilgjengelige.</p>}
  </div>;
}
