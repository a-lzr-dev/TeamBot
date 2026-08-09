from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, datetime_now

# ============ МОДЕЛИ ДЛЯ МЕНЮ ДЕЙСТВИЙ (AVANPOST) ============


class UserMenuActionItemModel(BaseModel):
    """Модель для дерева пунктов меню действий"""

    __tablename__ = "TUsersMenusActionsItems"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_UsersMenusActionsItems"),
        ForeignKeyConstraint(
            ["FK_ParentItem"],
            ["TUsersMenusActionsItems.FID"],
            ondelete="SET NULL",
            name="FK_UsersMenusActionsItems_Parent",
        ),
        Index("IX_UsersMenusActionsItems_ParentID", "FK_ParentItem"),
        Index("IX_UsersMenusActionsItems_Order", "FSortOrder"),
        Index("IX_UsersMenusActionsItems_IsActive", "FIsActive"),
        UniqueConstraint("FName", name="UK_UsersMenusActionsItems_Name"),
    )

    FID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    FK_ParentItem: Mapped[int | None] = mapped_column(Integer, nullable=True)

    FName: Mapped[str] = mapped_column(String(200), nullable=False)
    FDescription: Mapped[str | None] = mapped_column(Text, nullable=True)

    FItemType: Mapped[str] = mapped_column(String(20), default="action")  # action, folder, separator, url
    FAction: Mapped[str | None] = mapped_column(String(200), nullable=True)
    FActionParams: Mapped[str | None] = mapped_column(Text, nullable=True)

    FHasSubItems: Mapped[bool] = mapped_column(Boolean, default=False)
    FLevel: Mapped[int] = mapped_column(Integer, default=0)
    FSortOrder: Mapped[int] = mapped_column(Integer, default=0)

    FIcon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    FEmoji: Mapped[str | None] = mapped_column(String(10), nullable=True)

    FIsActive: Mapped[bool] = mapped_column(Boolean, default=True)
    FIsVisible: Mapped[bool] = mapped_column(Boolean, default=True)
    FRequiresAuth: Mapped[bool] = mapped_column(Boolean, default=True)
    FRequiresAdmin: Mapped[bool] = mapped_column(Boolean, default=False)

    FUrl: Mapped[str | None] = mapped_column(String(500), nullable=True)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)
    FCreatedBy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Связи с добавленным параметром overlaps для подавления предупреждения
    parent_item: Mapped[Optional["UserMenuActionItemModel"]] = relationship(
        "UserMenuActionItemModel",
        remote_side=[FID],
        foreign_keys=[FK_ParentItem],
        primaryjoin="UserMenuActionItemModel.FID == UserMenuActionItemModel.FK_ParentItem",
        uselist=False,
        overlaps="child_items",
    )

    child_items: Mapped[list["UserMenuActionItemModel"]] = relationship(
        "UserMenuActionItemModel",
        remote_side=[FK_ParentItem],
        foreign_keys=[FK_ParentItem],
        primaryjoin="UserMenuActionItemModel.FK_ParentItem == UserMenuActionItemModel.FID",
        uselist=True,
        overlaps="parent_item",
    )

    def __repr__(self) -> str:
        return f"<UserMenuActionItemModel(id={self.FID}, name={self.FName}, type={self.FItemType})>"

    @property
    def display_name(self) -> str:
        prefix = self.FEmoji or "📌"
        return f"{prefix} {self.FName}"

    @property
    def is_action(self) -> bool:
        return self.FItemType == "action"  # type: ignore[no-any-return]

    @property
    def is_folder(self) -> bool:
        return self.FItemType == "folder"  # type: ignore[no-any-return]

    @property
    def is_separator(self) -> bool:
        return self.FItemType == "separator"  # type: ignore[no-any-return]

    @property
    def is_url(self) -> bool:
        return self.FItemType == "url"  # type: ignore[no-any-return]

    @property
    def has_children(self) -> bool:
        return bool(self.FHasSubItems)

    def to_dict(self, include_children: bool = False) -> dict[str, Any]:
        """Преобразование в словарь с поддержкой вложенности"""
        data: dict[str, Any] = {
            "id": self.FID,
            "name": self.FName,
            "display_name": self.display_name,
            "type": self.FItemType,
            "has_subitems": bool(self.FHasSubItems),
            "level": self.FLevel,
            "emoji": self.FEmoji,
            "requires_admin": self.FRequiresAdmin,
            "is_active": self.FIsActive,
            "is_visible": self.FIsVisible,
            "sort_order": self.FSortOrder,
        }

        if self.FAction:
            data["action"] = self.FAction

        if self.FActionParams:
            data["action_params"] = self.FActionParams

        if self.FUrl:
            data["url"] = self.FUrl

        if self.FDescription:
            data["description"] = self.FDescription

        if self.FIcon:
            data["icon"] = self.FIcon

        if include_children and self.child_items:
            data["children"] = [child.to_dict(include_children=False) for child in self.child_items]

        return data

    def to_telegram_dict(self) -> dict[str, Any]:
        """Преобразование для Telegram бота"""
        return {
            "id": self.FID,
            "name": self.FName,
            "display_name": self.display_name,
            "has_subitems": bool(self.FHasSubItems),
            "type": self.FItemType,
            "requires_admin": self.FRequiresAdmin,
        }


# ============ ЭКСПОРТ ============

__all__ = [
    "UserMenuActionItemModel",
]
