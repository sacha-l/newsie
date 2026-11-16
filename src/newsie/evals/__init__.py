"""Gold-set loading and the label-swap check."""

from newsie.evals.gold import load_gold
from newsie.evals.label_swap import label_swap_ok, render_attributed

__all__ = ["label_swap_ok", "load_gold", "render_attributed"]
