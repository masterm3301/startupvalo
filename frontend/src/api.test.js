import { expect, it } from "vitest";
import { parseSSE } from "./api";

it("parses complete events and keeps the partial tail", () => {
  const [events, rest] = parseSSE('data: {"type":"a"}\n\ndata: {"ty');
  expect(events).toEqual([{ type: "a" }]);
  expect(rest).toBe('data: {"ty');
});

it("parses multiple events in one chunk", () => {
  const [events, rest] = parseSSE('data: {"n":1}\n\ndata: {"n":2}\n\n');
  expect(events.map((e) => e.n)).toEqual([1, 2]);
  expect(rest).toBe("");
});

it("ignores non-data lines", () => {
  const [events] = parseSSE(': keepalive\n\ndata: {"n":3}\n\n');
  expect(events).toEqual([{ n: 3 }]);
});
