import json
import re
from pathlib import Path
from typing import Optional

import numpy as np
from src.models.clip_candidate import ClipCandidate, ViralScore


class CurationService:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)

    def score_by_audio_energy(
        self, energy_values: list[float]
    ) -> ViralScore:
        if not energy_values:
            return ViralScore(overall=50, reasoning="No audio data available")

        arr = np.array(energy_values)
        peak_ratio = float(np.sum(arr > np.mean(arr) + np.std(arr)) / len(arr))
        max_energy = float(np.max(arr))
        mean_energy = float(np.mean(arr))

        energy_score = min(100, peak_ratio * 200)
        intensity_score = min(100, (max_energy - mean_energy) * 10 + 50)
        overall = (energy_score * 0.4 + intensity_score * 0.6)

        return ViralScore(
            overall=round(overall, 1),
            humor=round(min(100, max(0, energy_score + 10)), 1),
            emotion=round(min(100, max(0, intensity_score)), 1),
            relevance=70.0,
            hook_strength=round(min(100, max(0, peak_ratio * 150)), 1),
            reasoning=f"Peak ratio: {peak_ratio:.2f}, max energy: {max_energy:.1f}",
        )

    def score_by_transcript(
        self, transcript: str
    ) -> ViralScore:
        if not transcript:
            return ViralScore(overall=50, reasoning="No transcript available")

        sentences = re.split(r'[.!?]+', transcript)
        sentence_lengths = [len(s.split()) for s in sentences if s.strip()]
        if not sentence_lengths:
            return ViralScore(overall=50, reasoning="Empty transcript after split")

        excitement_words = {
            "wow", "oh", "no", "what", "did you see", "look at",
            "inacreditável", "caramba", "nossa", "olha", "não acredito",
            "puts", "mano", "cara", "véi", "raça", "mermão",
        }
        question_words = {"?", "what", "who", "how", "why", "onde", "quem", "como"}
        laughter_patterns = [r'\bh+a+h+a+\b', r'\bkkk+\b', r'\brs+\b', r'\blol\b',
                             r'\bh+e+h+e+\b', r'\bhehe\b', r'\bhuahu+\b', r'\bkkj+\b']

        transcript_lower = transcript.lower()
        excitement_count = sum(
            1 for w in excitement_words if w in transcript_lower
        )
        question_count = sum(
            1 for s in sentences if any(q in s.lower() for q in question_words)
        )
        laughter_count = sum(
            len(re.findall(p, transcript_lower))
            for p in laughter_patterns
        )

        excitement_score = min(100, excitement_count * 15)
        engagement_score = min(100, question_count * 10)
        humor_score = min(100, laughter_count * 20 + excitement_score * 0.3)

        hook_score = 0
        if sentences:
            first_words = sentences[0].split()
            if any(w in first_words[0].lower() for w in ["wow", "oh", "no", "what", "look", "olha", "nossa", "caramba"]):
                hook_score = 80
            elif any(c in "!?" for c in sentences[0]):
                hook_score = 70
            else:
                hook_score = 40

        overall = (excitement_score * 0.25 + engagement_score * 0.2
                   + humor_score * 0.3 + hook_score * 0.25)

        return ViralScore(
            overall=round(overall, 1),
            humor=round(min(100, humor_score), 1),
            emotion=round(min(100, excitement_score), 1),
            relevance=round(min(100, engagement_score + 50), 1),
            hook_strength=round(hook_score, 1),
            reasoning=f"Excitement: {excitement_score:.0f}, humor: {humor_score:.0f}, "
                      f"hook: {hook_score:.0f}, questions: {question_count}",
        )

    def rank_candidates(
        self,
        candidates: list[ViralScore],
        min_score: float = 60.0,
        max_results: int = 10,
    ) -> list[tuple[int, ViralScore]]:
        scored = [(i, s) for i, s in enumerate(candidates) if s.overall >= min_score]
        scored.sort(key=lambda x: x[1].overall, reverse=True)
        return scored[:max_results]

    def select_daily_picks(
        self,
        candidates: list[tuple[ClipCandidate, ViralScore]],
        max_picks: int = 5,
    ) -> list[tuple[ClipCandidate, ViralScore]]:
        valid = [(c, s) for c, s in candidates
                 if 15 <= c.duration_seconds <= 90]
        valid.sort(key=lambda x: x[1].overall, reverse=True)
        return valid[:max_picks]
