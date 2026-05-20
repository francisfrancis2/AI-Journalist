import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 300;

const BACKEND = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const DEEP_RESEARCH_PROXY_TIMEOUT_MS = 240_000;

type RouteContext = {
  params: Promise<{ storyId: string }>;
};

function jsonError(detail: string, status: number): NextResponse {
  return NextResponse.json({ detail }, { status });
}

function forwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  headers.set("content-type", request.headers.get("content-type") ?? "application/json");

  const authorization = request.headers.get("authorization");
  if (authorization) {
    headers.set("authorization", authorization);
  }

  const cookie = request.headers.get("cookie");
  if (cookie) {
    headers.set("cookie", cookie);
  }

  return headers;
}

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { storyId } = await context.params;
  const body = await request.text();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEEP_RESEARCH_PROXY_TIMEOUT_MS);

  try {
    const backendResponse = await fetch(
      `${BACKEND}/api/v1/stories/${encodeURIComponent(storyId)}/deep-research`,
      {
        method: "POST",
        headers: forwardHeaders(request),
        body,
        signal: controller.signal,
        cache: "no-store",
      }
    );

    const responseBody = await backendResponse.text();
    const contentType = backendResponse.headers.get("content-type") ?? "application/json";

    return new NextResponse(responseBody, {
      status: backendResponse.status,
      headers: {
        "content-type": contentType,
        "x-ai-journalist-proxy": "deep-research-route",
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return jsonError(
        "Additional research is taking longer than expected. Please try a narrower research request.",
        504
      );
    }

    return jsonError("Could not connect to the research service. Please try again.", 502);
  } finally {
    clearTimeout(timeout);
  }
}
