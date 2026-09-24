# Draft intervention — RAGFlow #20148

Do not post as project promotion. The useful contribution is the measured retrieval cutoff behavior.

Suggested comment:

The dropped-candidate trace would be useful for more than tuning thresholds. I ran a controlled retrieval experiment where the one source that changed the evidence verdict ranked **17th** in two separate corpora. With a visible top_k=5 it disappeared completely; when the same ranking was used only as reading order and the late source remained eligible, the contradiction was recovered.

That suggests one extra field in the proposed debug payload may be valuable: keep enough rank/cutoff information to answer not only “below threshold?” but “where would this candidate have ranked before the eligibility cutoff?”

For a dropped candidate I would ideally want:

- chunk_id
- pre-cutoff rank
- similarity / vector_similarity / term_similarity
- applied threshold
- top_k cutoff
- reason: threshold | top_k | reranker | other
- selected: false

Then a retrieval regression case can distinguish “the retriever never found the evidence” from “it found it at rank 17 and the policy hid it”. Those need different fixes.

I have a deterministic fixture for the rank-17 case if a regression test would help the PR.
