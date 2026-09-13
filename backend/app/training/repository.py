from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrainingDataset, TrainingDatasetReview, TrainingDatasetRevision


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dataset(self, dataset_id: UUID) -> TrainingDataset | None:
        return await self.session.get(TrainingDataset, dataset_id, populate_existing=True)

    async def revision(self, dataset_id: UUID, revision_id: UUID) -> TrainingDatasetRevision | None:
        result: TrainingDatasetRevision | None = await self.session.scalar(
            select(TrainingDatasetRevision).where(
                TrainingDatasetRevision.dataset_id == dataset_id,
                TrainingDatasetRevision.id == revision_id,
            )
        )

        return result

    async def latest_review(self, revision_id: UUID) -> TrainingDatasetReview | None:
        result: TrainingDatasetReview | None = await self.session.scalar(
            select(TrainingDatasetReview)
            .where(
                TrainingDatasetReview.revision_id == revision_id,
            )
            .order_by(TrainingDatasetReview.sequence.desc())
            .limit(1)
        )

        return result

    async def next_revision(self, dataset_id: UUID) -> int:
        current = await self.session.scalar(
            select(func.max(TrainingDatasetRevision.revision_number)).where(
                TrainingDatasetRevision.dataset_id == dataset_id
            )
        )
        return (current or 0) + 1

    async def datasets(self, limit: int, offset: int) -> list[TrainingDataset]:
        return list(
            await self.session.scalars(
                select(TrainingDataset)
                .order_by(TrainingDataset.created_at.desc(), TrainingDataset.id)
                .limit(limit)
                .offset(offset)
            )
        )

    async def revisions(
        self, dataset_id: UUID, limit: int, offset: int
    ) -> list[TrainingDatasetRevision]:
        return list(
            await self.session.scalars(
                select(TrainingDatasetRevision)
                .where(
                    TrainingDatasetRevision.dataset_id == dataset_id,
                )
                .order_by(TrainingDatasetRevision.revision_number.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    async def reviews(
        self, revision_id: UUID, limit: int, offset: int
    ) -> list[TrainingDatasetReview]:
        return list(
            await self.session.scalars(
                select(TrainingDatasetReview)
                .where(
                    TrainingDatasetReview.revision_id == revision_id,
                )
                .order_by(TrainingDatasetReview.sequence)
                .limit(limit)
                .offset(offset)
            )
        )
