import { NextRequest } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const url = new URL(req.url);
    // backend container is accessible as "backend" port 8000
    const backendUrl = `http://backend:8000/workspace/upload-to${url.search}`;
    
    // Check if body is present
    if (!req.body) {
      return new Response("No request body found", { status: 400 });
    }

    const response = await fetch(backendUrl, {
      method: "POST",
      headers: {
        "content-type": req.headers.get("content-type") || "",
      },
      body: req.body,
      // @ts-ignore
      duplex: "half",
    });

    // Pipe the response back
    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  } catch (error) {
    console.error("Proxy upload error:", error);
    return new Response("Internal Server Error during proxy", { status: 500 });
  }
}
