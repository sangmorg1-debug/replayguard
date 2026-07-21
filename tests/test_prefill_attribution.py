from replayguard.prefill_attribution import PrefillSignals, attribute


class FakeBackend:
    model_id = "fake"; revision = "test"
    def __init__(self): self.calls = 0
    def signals(self, prefix, steps):
        self.calls += 1; size = len(steps)
        nll = tuple([1.0, 1.2, 5.0][:size])
        attention = tuple(tuple(0.9 if j == 0 and j < i else 0.1 if j < i else 0 for j in range(size)) for i in range(size))
        return PrefillSignals(nll, attention, 20)


def test_two_prefill_passes_route_late_symptom_to_earlier_source():
    backend = FakeBackend(); candidates, evidence = attribute(
        [("s1", "wrong assumption"), ("s2", "work"), ("s3", "ERROR final failure")], backend,
        symptom_ratio=.34, max_candidates=1)
    assert backend.calls == 2 and evidence["decoded_tokens"] == 0
    assert candidates[0].location == "s1" and candidates[0].evidence[0].related_locations == ("s3",)


def test_empty_trace_needs_no_model_call():
    candidates, evidence = attribute([], FakeBackend())
    assert candidates == [] and evidence["prefill_passes"] == 0
