import { IdeationWorkspace } from "@/components/IdeationWorkspace";

export default async function AnglesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <IdeationWorkspace storyId={id} stage="angles" />;
}
