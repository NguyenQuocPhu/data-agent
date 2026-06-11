import random

class EvolutionHyperparams:
    def __init__(self, epiplexity_min=0.5, epiplexity_max=1.8, vocab_dropout_rate=0.15):
        self.epiplexity_min = epiplexity_min
        self.epiplexity_max = epiplexity_max
        self.vocab_dropout_rate = vocab_dropout_rate

    def apply_evolutionary_drift(self, noise_level=0.1):
        """
        [SOTA] Kích hoạt Evolutionary Drift (Trôi dạt tiến hóa)
        Áp dụng nhiễu Gaussian để tránh hội tụ sớm (premature convergence).
        """
        # Cập nhật ngưỡng Goldilocks Zone
        self.epiplexity_min = max(0.1, self.epiplexity_min + random.gauss(0, noise_level))
        self.epiplexity_max = max(self.epiplexity_min + 0.1, self.epiplexity_max + random.gauss(0, noise_level))
        
        # Cập nhật tỷ lệ chống "AI lười biếng"
        self.vocab_dropout_rate = max(0.05, min(0.5, self.vocab_dropout_rate + random.gauss(0, noise_level / 2)))
        
        print(f"🧬 [Evolutionary Drift] Đã cập nhật ADN: Epi[{self.epiplexity_min:.2f}-{self.epiplexity_max:.2f}], Vocab_Dropout: {self.vocab_dropout_rate:.2f}")

    def to_dict(self):
        return {
            "epiplexity_min": self.epiplexity_min,
            "epiplexity_max": self.epiplexity_max,
            "vocab_dropout_rate": self.vocab_dropout_rate
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            epiplexity_min=data.get("epiplexity_min", 0.5),
            epiplexity_max=data.get("epiplexity_max", 1.8),
            vocab_dropout_rate=data.get("vocab_dropout_rate", 0.15)
        )

# Global singleton instance
HYPERPARAMS = EvolutionHyperparams()
