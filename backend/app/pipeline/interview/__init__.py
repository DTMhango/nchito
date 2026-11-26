"""Interview pack (DESIGN.md 10.3a): versioned sections per application, truth-checked like documents."""

from app.apply import resolvers

# An approved "build the interview pack?" offer queues the pack (see ``offer.accept_offer``).
resolvers.register_lazy("interview_pack_offer", "app.pipeline.interview.offer:accept_offer")
