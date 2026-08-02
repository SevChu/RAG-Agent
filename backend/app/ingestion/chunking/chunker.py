from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from app.ingestion.chunking.models import (
    ChunkingConfig,
    ChunkingContext,
    ChunkingResult,
    ChunkingStats,
    ChunkSourceMetadata,
    ChunkWarning,
    DocumentChunk,
)
from app.ingestion.chunking.tokens import EstimatedTokenCounter
from app.ingestion.models import BlockKind, ExtractionMethod, ParsedBlock, ParsedDocument


@dataclass(frozen=True, slots=True)
class _AtomicUnit:
    text: str
    block_indices: tuple[int, ...]
    kinds: tuple[BlockKind, ...]
    protected: bool
    allow_partial_overlap: bool = True
    overlap_token_count: int = 0


@dataclass(frozen=True, slots=True)
class _SectionGroup:
    section_path: tuple[str, ...]
    context_block_indices: tuple[int, ...]
    units: tuple[_AtomicUnit, ...]


class StructuredDocumentChunker:
    def __init__(self, token_counter: EstimatedTokenCounter | None = None) -> None:
        self._tokens = token_counter or EstimatedTokenCounter()

    def chunk(
        self,
        document: ParsedDocument,
        *,
        config: ChunkingConfig | None = None,
        context: ChunkingContext | None = None,
    ) -> ChunkingResult:
        actual_config = config or ChunkingConfig()
        actual_context = context or ChunkingContext()
        warnings: list[ChunkWarning] = []
        chunks: list[DocumentChunk] = []

        for group in self._section_groups(document):
            self._chunk_section(
                document=document,
                group=group,
                config=actual_config,
                context=actual_context,
                chunks=chunks,
                warnings=warnings,
            )

        if not chunks:
            raise ValueError("The parsed document did not produce any chunks.")
        covered_blocks = {
            index for chunk in chunks for index in chunk.source.source_block_indices
        }
        uncovered_blocks = tuple(
            sorted(set(range(len(document.blocks))) - covered_blocks)
        )
        if uncovered_blocks:
            warnings.append(
                ChunkWarning(
                    code="SOURCE_COVERAGE_GAP",
                    message="Some parsed source blocks are not represented by any chunk.",
                    section_path=(),
                    source_block_indices=uncovered_blocks,
                )
            )
        stats = self._stats(document, chunks, warnings, actual_config)
        return ChunkingResult(
            document=document,
            config=actual_config,
            chunks=tuple(chunks),
            stats=stats,
            warnings=tuple(warnings),
        )

    def _chunk_section(
        self,
        *,
        document: ParsedDocument,
        group: _SectionGroup,
        config: ChunkingConfig,
        context: ChunkingContext,
        chunks: list[DocumentChunk],
        warnings: list[ChunkWarning],
    ) -> None:
        prefix = self._section_prefix(group.section_path)
        prefix_tokens = self._tokens.count(prefix)
        if prefix_tokens >= config.target_tokens:
            warnings.append(
                ChunkWarning(
                    code="SECTION_CONTEXT_OVER_TARGET",
                    message="The section heading context alone reaches the target size.",
                    section_path=group.section_path,
                    source_block_indices=group.context_block_indices,
                )
            )

        if not group.units:
            self._emit_chunk(
                document=document,
                group=group,
                prefix=prefix,
                units=(),
                context=context,
                chunks=chunks,
            )
            return

        current: list[_AtomicUnit] = []
        for unit in group.units:
            available_content_tokens = max(1, config.target_tokens - prefix_tokens)
            unit_tokens = self._tokens.count(unit.text)
            if unit_tokens > available_content_tokens and not unit.protected:
                if current:
                    self._warn_if_protected_over_target(
                        units=tuple(current),
                        prefix=prefix,
                        group=group,
                        config=config,
                        chunk_index=len(chunks),
                        warnings=warnings,
                    )
                    self._emit_chunk(
                        document=document,
                        group=group,
                        prefix=prefix,
                        units=tuple(current),
                        context=context,
                        chunks=chunks,
                    )
                    current = []
                paragraph_overlap = (
                    min(
                        config.overlap_tokens,
                        max(0, available_content_tokens - 1),
                    )
                    if unit.allow_partial_overlap
                    else 0
                )
                for segment_text, overlap_count in self._tokens.split(
                    unit.text,
                    max_tokens=available_content_tokens,
                    overlap_tokens=paragraph_overlap,
                ):
                    segment = _AtomicUnit(
                        text=segment_text,
                        block_indices=unit.block_indices,
                        kinds=unit.kinds,
                        protected=False,
                        allow_partial_overlap=unit.allow_partial_overlap,
                        overlap_token_count=overlap_count,
                    )
                    self._emit_chunk(
                        document=document,
                        group=group,
                        prefix=prefix,
                        units=(segment,),
                        context=context,
                        chunks=chunks,
                    )
                continue

            if not current or self._fits(prefix, (*current, unit), config):
                current.append(unit)
                continue

            previous_units = tuple(current)
            self._warn_if_protected_over_target(
                units=previous_units,
                prefix=prefix,
                group=group,
                config=config,
                chunk_index=len(chunks),
                warnings=warnings,
            )
            self._emit_chunk(
                document=document,
                group=group,
                prefix=prefix,
                units=previous_units,
                context=context,
                chunks=chunks,
            )
            current = []
            if unit.protected and not self._fits(prefix, (unit,), config):
                self._warn_if_protected_over_target(
                    units=(unit,),
                    prefix=prefix,
                    group=group,
                    config=config,
                    chunk_index=len(chunks),
                    warnings=warnings,
                )
                self._emit_chunk(
                    document=document,
                    group=group,
                    prefix=prefix,
                    units=(unit,),
                    context=context,
                    chunks=chunks,
                )
                continue

            overlap_budget = max(
                0,
                min(
                    config.overlap_tokens,
                    config.target_tokens - prefix_tokens - unit_tokens,
                ),
            )
            overlap = self._overlap_unit(previous_units, overlap_budget)
            if overlap is not None:
                current.append(overlap)
            current.append(unit)

        if current:
            self._warn_if_protected_over_target(
                units=tuple(current),
                prefix=prefix,
                group=group,
                config=config,
                chunk_index=len(chunks),
                warnings=warnings,
            )
            self._emit_chunk(
                document=document,
                group=group,
                prefix=prefix,
                units=tuple(current),
                context=context,
                chunks=chunks,
            )

    def _warn_if_protected_over_target(
        self,
        *,
        units: tuple[_AtomicUnit, ...],
        prefix: str,
        group: _SectionGroup,
        config: ChunkingConfig,
        chunk_index: int,
        warnings: list[ChunkWarning],
    ) -> None:
        if len(units) != 1 or not units[0].protected:
            return
        available_content_tokens = max(
            1, config.target_tokens - self._tokens.count(prefix)
        )
        if self._tokens.count(units[0].text) <= available_content_tokens:
            return
        warnings.append(
            ChunkWarning(
                code="PROTECTED_UNIT_OVER_TARGET",
                message=(
                    "A protected structural unit exceeds the target and was kept intact."
                ),
                section_path=group.section_path,
                source_block_indices=units[0].block_indices,
                chunk_index=chunk_index,
            )
        )

    def _emit_chunk(
        self,
        *,
        document: ParsedDocument,
        group: _SectionGroup,
        prefix: str,
        units: tuple[_AtomicUnit, ...],
        context: ChunkingContext,
        chunks: list[DocumentChunk],
    ) -> None:
        content = "\n\n".join(unit.text for unit in units if unit.text.strip())
        text = "\n\n".join(part for part in (prefix, content) if part).strip()
        content_indices = tuple(
            sorted({index for unit in units for index in unit.block_indices})
        )
        source_indices = tuple(
            sorted({*group.context_block_indices, *content_indices})
        )
        if not source_indices:
            raise ValueError("A chunk must retain source block lineage.")
        source_blocks = [document.blocks[index] for index in source_indices]
        content_blocks = [
            document.blocks[index]
            for index in (content_indices or group.context_block_indices)
        ]
        source = ChunkSourceMetadata(
            course_id=context.course_id,
            document_id=context.document_id,
            file_name=document.file_name,
            file_type=document.file_type,
            parser_name=document.parser_name,
            section_path=group.section_path,
            source_block_start=min(source_indices),
            source_block_end=max(source_indices),
            source_block_indices=source_indices,
            context_block_indices=group.context_block_indices,
            block_kinds=tuple(dict.fromkeys(block.kind for block in content_blocks)),
            line_start=self._minimum_location(source_blocks, "line_start"),
            line_end=self._maximum_location(source_blocks, "line_end"),
            page_numbers=self._location_values(source_blocks, "page_number"),
            slide_numbers=self._location_values(source_blocks, "slide_number"),
            extraction_methods=tuple(
                dict.fromkeys(
                    method
                    for block in source_blocks
                    if (method := block.source.extraction_method) is not None
                )
            ),
            minimum_ocr_confidence=self._minimum_ocr_confidence(source_blocks),
        )
        chunks.append(
            DocumentChunk(
                chunk_index=len(chunks),
                text=text,
                estimated_token_count=self._tokens.count(text),
                overlap_token_count=sum(unit.overlap_token_count for unit in units),
                source=source,
            )
        )

    @staticmethod
    def _minimum_ocr_confidence(blocks: list[ParsedBlock]) -> float | None:
        confidences = [
            block.source.confidence
            for block in blocks
            if block.source.extraction_method is ExtractionMethod.OCR
            and block.source.confidence is not None
        ]
        return min(confidences, default=None)

    def _section_groups(self, document: ParsedDocument) -> tuple[_SectionGroup, ...]:
        groups: list[_SectionGroup] = []
        current_path: tuple[str, ...] | None = None
        current_context: tuple[int, ...] = ()
        current_blocks: list[ParsedBlock] = []
        last_heading_path: tuple[str, ...] = ()
        active_heading_indices: list[int] = []

        def flush(*, include_empty: bool = False) -> None:
            nonlocal current_blocks
            if current_path is None or (not current_blocks and not include_empty):
                return
            units = self._atomic_units(current_blocks)
            groups.append(
                _SectionGroup(
                    section_path=current_path,
                    context_block_indices=current_context,
                    units=units,
                )
            )
            current_blocks = []

        for block in document.blocks:
            if self._is_context_heading(block):
                new_path = block.section_path
                if current_path is not None:
                    is_parent_of_new_section = (
                        current_path != new_path
                        and len(current_path) < len(new_path)
                        and new_path[: len(current_path)] == current_path
                    )
                    flush(include_empty=not is_parent_of_new_section)
                depth = len(new_path)
                active_heading_indices = active_heading_indices[: depth - 1]
                active_heading_indices.append(block.source.block_index)
                current_path = new_path
                current_context = tuple(active_heading_indices)
                last_heading_path = new_path
                continue
            block_path = block.section_path or last_heading_path
            if current_path is None:
                current_path = block_path
                current_context = (
                    tuple(active_heading_indices[: len(block_path)])
                    if block_path == last_heading_path
                    else ()
                )
            elif block_path != current_path:
                flush(include_empty=True)
                current_path = block_path
                current_context = (
                    tuple(active_heading_indices[: len(block_path)])
                    if block_path == last_heading_path
                    else ()
                )
            current_blocks.append(block)
        flush(include_empty=True)

        if groups:
            return tuple(groups)
        raise ValueError("The parsed document contains no chunkable blocks.")

    def _atomic_units(self, blocks: list[ParsedBlock]) -> tuple[_AtomicUnit, ...]:
        return tuple(
            _AtomicUnit(
                text=block.text,
                block_indices=(block.source.block_index,),
                kinds=(block.kind,),
                protected=block.kind
                in {
                    BlockKind.LIST,
                    BlockKind.CODE,
                    BlockKind.TABLE,
                    BlockKind.IMAGE,
                    BlockKind.FORMULA,
                    BlockKind.HEADING,
                },
                allow_partial_overlap=(
                    block.source.extraction_method is not ExtractionMethod.OCR
                ),
            )
            for block in blocks
        )

    def _overlap_unit(
        self,
        units: tuple[_AtomicUnit, ...],
        budget: int,
    ) -> _AtomicUnit | None:
        if budget < 1:
            return None
        texts: list[str] = []
        block_indices: list[int] = []
        remaining = budget
        for unit in reversed(units):
            if unit.protected:
                break
            unit_tokens = self._tokens.count(unit.text)
            if unit_tokens <= remaining:
                texts.insert(0, unit.text)
                block_indices[0:0] = unit.block_indices
                remaining -= unit_tokens
            else:
                if not unit.allow_partial_overlap:
                    break
                suffix = self._tokens.suffix(unit.text, remaining)
                if suffix:
                    texts.insert(0, suffix)
                    block_indices[0:0] = unit.block_indices
                remaining = 0
            if remaining == 0:
                break
        text = "\n\n".join(texts).strip()
        if not text:
            return None
        overlap_count = self._tokens.count(text)
        return _AtomicUnit(
            text=text,
            block_indices=tuple(dict.fromkeys(block_indices)),
            kinds=(BlockKind.PARAGRAPH,),
            protected=False,
            overlap_token_count=overlap_count,
        )

    def _fits(
        self,
        prefix: str,
        units: tuple[_AtomicUnit, ...],
        config: ChunkingConfig,
    ) -> bool:
        content = "\n\n".join(unit.text for unit in units)
        text = "\n\n".join(part for part in (prefix, content) if part)
        return self._tokens.count(text) <= config.target_tokens

    @staticmethod
    def _is_context_heading(block: ParsedBlock) -> bool:
        return (
            block.kind is BlockKind.HEADING
            and bool(block.section_path)
            and block.text == block.section_path[-1]
        )

    @staticmethod
    def _section_prefix(section_path: tuple[str, ...]) -> str:
        return "\n".join(
            f"{'#' * min(level, 6)} {heading}"
            for level, heading in enumerate(section_path, start=1)
        )

    @staticmethod
    def _location_values(
        blocks: list[ParsedBlock],
        attribute: str,
    ) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    value
                    for block in blocks
                    if (value := getattr(block.source, attribute)) is not None
                }
            )
        )

    @classmethod
    def _minimum_location(
        cls,
        blocks: list[ParsedBlock],
        attribute: str,
    ) -> int | None:
        values = cls._location_values(blocks, attribute)
        return min(values, default=None)

    @classmethod
    def _maximum_location(
        cls,
        blocks: list[ParsedBlock],
        attribute: str,
    ) -> int | None:
        values = cls._location_values(blocks, attribute)
        return max(values, default=None)

    @staticmethod
    def _stats(
        document: ParsedDocument,
        chunks: list[DocumentChunk],
        warnings: list[ChunkWarning],
        config: ChunkingConfig,
    ) -> ChunkingStats:
        lengths = [chunk.estimated_token_count for chunk in chunks]
        overlaps = [chunk.overlap_token_count for chunk in chunks]
        covered_blocks = {
            index for chunk in chunks for index in chunk.source.source_block_indices
        }
        return ChunkingStats(
            source_block_count=len(document.blocks),
            covered_source_blocks=len(covered_blocks),
            uncovered_source_blocks=len(document.blocks) - len(covered_blocks),
            chunk_count=len(chunks),
            min_estimated_tokens=min(lengths),
            max_estimated_tokens=max(lengths),
            average_estimated_tokens=round(fmean(lengths), 2),
            chunks_with_overlap=sum(value > 0 for value in overlaps),
            average_overlap_tokens=round(fmean(overlaps), 2),
            over_target_chunks=sum(value > config.target_tokens for value in lengths),
            protected_over_target_units=sum(
                warning.code == "PROTECTED_UNIT_OVER_TARGET" for warning in warnings
            ),
            anomaly_count=len(warnings),
        )
