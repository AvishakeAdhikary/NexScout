import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./client";

describe("api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "nexscout_csrf=csrf-123";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("echoes the CSRF cookie on mutating requests only", async () => {
    fetchMock.mockImplementation(async () => new Response("{}", { status: 200 }));
    await api("/cases", { method: "POST", body: { name: "x" } });
    await api("/cases");
    const [, post] = fetchMock.mock.calls[0];
    const [, get] = fetchMock.mock.calls[1];
    expect(post.headers["X-CSRF-Token"]).toBe("csrf-123");
    expect(get.headers["X-CSRF-Token"]).toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/cases");
  });

  it("turns problem+json into ApiError with the server's detail", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 404,
          code: "not_found",
          detail: "Case not found.",
          request_id: "r1",
        }),
        { status: 404 },
      ),
    );
    const err = await api("/cases/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).problem.detail).toBe("Case not found.");
  });

  it("reports network failures honestly", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const err = (await api("/cases").catch((e: unknown) => e)) as ApiError;
    expect(err.problem.code).toBe("network_error");
  });
});
