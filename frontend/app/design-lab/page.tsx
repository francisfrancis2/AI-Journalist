import Link from "next/link";
import { ArrowUpRight, Camera, Figma, Layers3 } from "lucide-react";
import { StoryCard } from "@/components/StoryCard";
import { ScriptViewer } from "@/components/ScriptViewer";
import {
  designFixturePendingStory,
  designFixtureScript,
  designFixtureStories,
  designFixtureStoryDetail,
} from "@/lib/design-fixtures";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.18em] text-gray-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-white">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-gray-800 text-gray-300",
    researching: "bg-blue-900/50 text-blue-300",
    analysing: "bg-cyan-900/50 text-cyan-300",
    writing_storyline: "bg-violet-900/50 text-violet-300",
    evaluating: "bg-amber-900/50 text-amber-300",
    scripting: "bg-emerald-900/50 text-emerald-300",
    completed: "bg-green-900/50 text-green-300",
    failed: "bg-red-900/50 text-red-300",
  };

  return (
    <span
      className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider ${styles[status] ?? "bg-gray-800 text-gray-300"}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function PipelineProgress({ status }: { status: string }) {
  const stages = [
    { status: "researching", label: "Researching the web" },
    { status: "analysing", label: "Analysing findings" },
    { status: "writing_storyline", label: "Crafting storyline" },
    { status: "evaluating", label: "Evaluating quality" },
    { status: "scripting", label: "Writing script" },
  ];
  const currentIdx = stages.findIndex((stage) => stage.status === status);

  return (
    <div className="rounded-3xl border border-gray-800 bg-gray-900 p-6">
      <h3 className="text-lg font-semibold text-white">Pipeline Progress</h3>
      <div className="mt-6 space-y-4">
        {stages.map((stage, idx) => {
          const done = idx < currentIdx;
          const active = idx === currentIdx;
          return (
            <div key={stage.status} className="flex items-center gap-3">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${
                  done
                    ? "bg-green-700 text-green-100"
                    : active
                      ? "bg-indigo-700 text-white"
                      : "bg-gray-800 text-gray-500"
                }`}
              >
                {done ? "✓" : idx + 1}
              </div>
              <span
                className={`text-sm ${
                  active ? "font-semibold text-white" : done ? "text-gray-400" : "text-gray-600"
                }`}
              >
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Frame({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white">{title}</h2>
          <p className="mt-1 text-sm text-gray-400">{hint}</p>
        </div>
      </div>
      <div className="rounded-[32px] border border-white/10 bg-[#0b1120] p-4 shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
        {children}
      </div>
    </section>
  );
}

export default async function DesignLabPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const exportMode = params.export === "1";

  return (
    <div className={exportMode ? "space-y-10" : "space-y-12"}>
      {!exportMode && (
        <section className="overflow-hidden rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_32%),linear-gradient(135deg,_rgba(17,24,39,0.95),_rgba(3,7,18,1))] p-8">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200">
              <Figma className="h-3.5 w-3.5" />
              Figma Handoff
            </div>
            <h1 className="mt-5 text-4xl font-bold tracking-tight text-white">
              Export-ready screens for redesign work
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-gray-300">
              This page gives you stable, polished app states you can screenshot or recreate in
              Figma. Open the export mode for clean capture surfaces, improve them in Figma, then
              send the file or node links back and I can map the designs into code.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                href="/design-lab?export=1"
                className="inline-flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-50"
              >
                <Camera className="h-4 w-4" />
                Open Clean Export Mode
              </Link>
              <a
                href="https://www.figma.com/files/"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-full border border-white/15 px-5 py-2.5 text-sm font-semibold text-white transition hover:border-white/30 hover:bg-white/5"
              >
                Open Figma
                <ArrowUpRight className="h-4 w-4" />
              </a>
            </div>
          </div>
          <div className="mt-8 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-sm font-semibold text-white">1. Capture</p>
              <p className="mt-2 text-sm text-gray-400">
                Use the export route as a visual reference for dashboard, story cards, and script
                detail states.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-sm font-semibold text-white">2. Improve in Figma</p>
              <p className="mt-2 text-sm text-gray-400">
                Rebuild the screens as editable frames, components, and tokens instead of relying
                on screenshot layers.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-sm font-semibold text-white">3. Send it back</p>
              <p className="mt-2 text-sm text-gray-400">
                Share the Figma file or node links and I can implement the improved designs back in
                this app.
              </p>
            </div>
          </div>
        </section>
      )}

      <Frame
        title="Dashboard State"
        hint="Use this as the reference for the landing dashboard, input form, and story card grid."
      >
        <div className="rounded-[24px] border border-gray-800 bg-gray-950 p-6">
          <div className="mx-auto max-w-5xl space-y-10">
            <section className="py-4 text-center">
              <p className="text-sm uppercase tracking-[0.3em] text-cyan-300">Autonomous newsroom</p>
              <h2 className="mt-4 text-4xl font-bold tracking-tight text-white">AI Journalist</h2>
              <p className="mx-auto mt-3 max-w-xl text-lg text-gray-400">
                Research the web, pressure-test the angle, and shape a production-ready
                documentary script.
              </p>
            </section>

            <section className="mx-auto max-w-2xl rounded-[28px] border border-gray-800 bg-gray-900 p-6">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Layers3 className="h-4 w-4 text-cyan-300" />
                New Story
              </div>
              <div className="mt-5 space-y-4">
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
                    Research Topic
                  </p>
                  <div className="rounded-2xl border border-gray-700 bg-gray-800 px-4 py-4 text-sm leading-6 text-gray-200">
                    How the race to build AI data centers is reshaping energy markets, chip demand,
                    and cloud competition
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-[1fr_auto]">
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
                      Documentary Tone
                    </p>
                    <div className="rounded-2xl border border-gray-700 bg-gray-800 px-4 py-3 text-sm text-gray-200">
                      Investigative
                    </div>
                  </div>
                  <div className="flex items-end">
                    <button className="w-full rounded-2xl bg-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 md:w-auto">
                      Start Research
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <section className="space-y-5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-[0.22em] text-gray-500">
                  Story Queue
                </h3>
                <p className="text-sm text-gray-500">3 example states</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {designFixtureStories.map((story) => (
                  <StoryCard key={story.id} story={story} />
                ))}
              </div>
            </section>
          </div>
        </div>
      </Frame>

      <Frame
        title="Story Detail State"
        hint="This frame combines a completed story summary with the full script reader."
      >
        <div className="rounded-[24px] border border-gray-800 bg-gray-950 p-6">
          <div className="mx-auto max-w-4xl space-y-6">
            <div className="rounded-[28px] border border-gray-800 bg-gray-900 p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm uppercase tracking-[0.2em] text-cyan-300">
                    Story Detail
                  </p>
                  <h3 className="mt-3 text-2xl font-bold text-white">
                    {designFixtureStoryDetail.title}
                  </h3>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
                    {designFixtureStoryDetail.topic}
                  </p>
                </div>
                <StatusBadge status={designFixtureStoryDetail.status} />
              </div>
              <div className="mt-6 grid gap-6 border-t border-gray-800 pt-6 sm:grid-cols-3">
                <Metric
                  label="Quality score"
                  value={`${(designFixtureStoryDetail.quality_score! * 100).toFixed(0)}%`}
                />
                <Metric
                  label="Duration"
                  value={`${designFixtureStoryDetail.estimated_duration_minutes} min`}
                />
                <Metric
                  label="Word count"
                  value={designFixtureStoryDetail.word_count!.toLocaleString()}
                />
              </div>
            </div>
            <ScriptViewer script={designFixtureScript} />
          </div>
        </div>
      </Frame>

      <Frame
        title="Pipeline Progress State"
        hint="Use this state in Figma for loading and workflow-progress explorations."
      >
        <div className="rounded-[24px] border border-gray-800 bg-gray-950 p-6">
          <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="rounded-[28px] border border-gray-800 bg-gray-900 p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm uppercase tracking-[0.2em] text-violet-300">
                    In Progress
                  </p>
                  <h3 className="mt-3 text-2xl font-bold text-white">
                    {designFixturePendingStory.title}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-gray-400">
                    {designFixturePendingStory.topic}
                  </p>
                </div>
                <StatusBadge status={designFixturePendingStory.status} />
              </div>
              <div className="mt-6 grid gap-6 border-t border-gray-800 pt-6 sm:grid-cols-3">
                <Metric label="Tone" value="Investigative" />
                <Metric label="Quality so far" value="72%" />
                <Metric label="Refinement cycle" value="1 / 2" />
              </div>
            </div>
            <PipelineProgress status={designFixturePendingStory.status} />
          </div>
        </div>
      </Frame>

      {!exportMode && (
        <section className="rounded-[32px] border border-white/10 bg-gray-900 p-8">
          <h2 className="text-2xl font-semibold text-white">Recommended workflow</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-gray-800 bg-gray-950 p-5">
              <p className="text-sm font-semibold text-white">Open export mode</p>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Visit <code>/design-lab?export=1</code> and capture the frames you want to redesign.
              </p>
            </div>
            <div className="rounded-2xl border border-gray-800 bg-gray-950 p-5">
              <p className="text-sm font-semibold text-white">Rebuild in Figma</p>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Trace the layouts into editable Figma frames, components, styles, and spacing
                tokens.
              </p>
            </div>
            <div className="rounded-2xl border border-gray-800 bg-gray-950 p-5">
              <p className="text-sm font-semibold text-white">Send node links back</p>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Once your design is ready, send me the Figma node URL and I can implement it back
                into this frontend.
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
