import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const backendUrl = `http://backend:8000/chat/completions${url.search}`;
    
    // Read the incoming JSON body
    const body = await req.text();

    const response = await fetch(backendUrl, {
      method: "POST",
      headers: {
        "Content-Type": req.headers.get("content-type") || "application/json",
        "Accept": "text/event-stream",
      },
      body: body,
    });

    // Pipe the response body directly back to the client to preserve SSE streaming
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
      },
    });
  } catch (error) {
    console.error("Proxy chat error:", error);
    return new Response("Internal Server Error during chat proxy", { status: 500 });
  }
}
