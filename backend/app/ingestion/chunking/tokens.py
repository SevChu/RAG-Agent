from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _TokenSpan:
    start: int
    end: int


class EstimatedTokenCounter:
    """Deterministic tokenizer-free estimate used before the embedding model exists."""

    _semantic_breaks = frozenset("。！？!?；;.")

    def count(self, text: str) -> int:
        return len(self._spans(text))

    def suffix(self, text: str, max_tokens: int) -> str:
        if max_tokens < 1:
            return ""
        spans = self._spans(text)
        if not spans:
            return ""
        start_span = spans[max(0, len(spans) - max_tokens)]
        return text[start_span.start :].strip()

    def semantic_suffix(self, text: str, max_tokens: int) -> str:
        """Return complete trailing sentences within a maximum overlap budget."""
        if max_tokens < 1:
            return ""
        spans = self._spans(text)
        if not spans:
            return ""
        desired_start = max(0, len(spans) - max_tokens)
        has_semantic_break = False
        for index, span in enumerate(spans):
            if text[span.end - 1] not in self._semantic_breaks:
                continue
            has_semantic_break = True
            sentence_start = index + 1
            if desired_start <= sentence_start < len(spans):
                return text[spans[sentence_start].start :].strip()
        if has_semantic_break:
            return ""
        return self.suffix(text, max_tokens)

    def split(
        self,
        text: str,
        *,
        max_tokens: int,
        overlap_tokens: int,
    ) -> tuple[tuple[str, int], ...]:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive.")
        if overlap_tokens < 0 or overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be between 0 and max_tokens - 1.")
        spans = self._spans(text)
        if len(spans) <= max_tokens:
            return ((text.strip(), 0),)

        segments: list[tuple[str, int]] = []
        start = 0
        previous_end = 0
        while start < len(spans):
            proposed_end = min(start + max_tokens, len(spans))
            end = self._semantic_end(text, spans, start, proposed_end)
            if end <= start:
                end = proposed_end
            segment = text[spans[start].start : spans[end - 1].end].strip()
            actual_overlap = max(0, previous_end - start) if segments else 0
            segments.append((segment, actual_overlap))
            if end == len(spans):
                break
            previous_end = end
            start = self._semantic_overlap_start(
                text,
                spans,
                segment_start=start,
                segment_end=end,
                overlap_tokens=overlap_tokens,
            )
        return tuple(segments)

    def _semantic_end(
        self,
        text: str,
        spans: tuple[_TokenSpan, ...],
        start: int,
        proposed_end: int,
    ) -> int:
        minimum_size = max(1, (proposed_end - start) // 2)
        minimum_end = start + minimum_size
        for end in range(proposed_end, minimum_end, -1):
            last_span = spans[end - 1]
            if text[last_span.end - 1] in self._semantic_breaks:
                return end
        for end in range(proposed_end, minimum_end, -1):
            last_span = spans[end - 1]
            if end < len(spans):
                gap = text[last_span.end : spans[end].start]
                if any(character.isspace() for character in gap):
                    return end
        return proposed_end

    def _semantic_overlap_start(
        self,
        text: str,
        spans: tuple[_TokenSpan, ...],
        *,
        segment_start: int,
        segment_end: int,
        overlap_tokens: int,
    ) -> int:
        if overlap_tokens == 0:
            return segment_end
        desired_start = max(segment_start + 1, segment_end - overlap_tokens)
        for index in range(desired_start - 1, segment_start - 1, -1):
            span = spans[index]
            if text[span.end - 1] in self._semantic_breaks:
                sentence_start = index + 1
                if sentence_start < segment_end:
                    return sentence_start
                break
        if text[spans[segment_end - 1].end - 1] in self._semantic_breaks:
            return segment_end
        return desired_start

    @staticmethod
    def _spans(text: str) -> tuple[_TokenSpan, ...]:
        spans: list[_TokenSpan] = []
        index = 0
        while index < len(text):
            character = text[index]
            if character.isspace():
                index += 1
                continue
            if EstimatedTokenCounter._is_cjk(character):
                spans.append(_TokenSpan(index, index + 1))
                index += 1
                continue
            if character.isalnum() or character == "_":
                word_end = index + 1
                while word_end < len(text):
                    next_character = text[word_end]
                    if not (next_character.isalnum() or next_character == "_"):
                        break
                    if EstimatedTokenCounter._is_cjk(next_character):
                        break
                    word_end += 1
                part_start = index
                while part_start < word_end:
                    part_end = min(part_start + 4, word_end)
                    spans.append(_TokenSpan(part_start, part_end))
                    part_start = part_end
                index = word_end
                continue
            spans.append(_TokenSpan(index, index + 1))
            index += 1
        return tuple(spans)

    @staticmethod
    def _is_cjk(character: str) -> bool:
        codepoint = ord(character)
        return (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
        )
