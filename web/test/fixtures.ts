export interface FakeEventSourceEvent {
  id: number;
  kind: string;
  level?: string;
  message?: string;
}

export function event(data: Partial<FakeEventSourceEvent>): FakeEventSourceEvent {
  return {
    id: 1,
    kind: "test",
    ...data,
  } as FakeEventSourceEvent;
}
