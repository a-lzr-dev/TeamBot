from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .main import UserModel


# ============ МОДЕЛИ ДЛЯ МЕНЮ ДЕЙСТВИЙ (AVANPOST) ============


class AvanpostDirLanguageModel(BaseModel):
    """Языки (TRSDirLanguages)"""

    __tablename__ = "TAvanpostDirLanguages"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirLanguages"),)

    FID: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FFlagDefault: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostDirContactGroupModel(BaseModel):
    """Группы контактов (TRSDirAppObjectsGroupsTypes)"""

    __tablename__ = "TAvanpostDirContactsGroups"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirContactsGroups"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FOrderBy: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostDirContactLinkTypeModel(BaseModel):
    """Типы связи (TRSDirAppContactsLinksTypes)"""

    __tablename__ = "TAvanpostDirContactsLinksTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirContactsLinksTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(32), nullable=False)


class AvanpostDirOperatorModel(BaseModel):
    """Операторы (TRSDirOperators)"""

    __tablename__ = "TAvanpostDirOperators"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirOperators"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FK_Country: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)


class AvanpostDirOwnerModel(BaseModel):
    """Организации (TRSDirAppUsersCompaniesRolesOwners)"""

    __tablename__ = "TAvanpostDirOwners"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirOwners"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(16), nullable=False)


class AvanpostDirOwnerMotorCadeModel(BaseModel):
    """Колонны (TRSDirAppUsersCompaniesMotorCades)"""

    __tablename__ = "TAvanpostDirOwnersMotorCades"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirOwnersMotorCades"),)

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(32), nullable=False)


class AvanpostDirFileTypeModel(BaseModel):
    """Типы файлов (TRSDirAppFilesTypes)"""

    __tablename__ = "TAvanpostDirFilesTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirFilesTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)


class AvanpostDirContactMsgDirectionTypeModel(BaseModel):
    """Направления сообщений (TRSDirAppMsgsDirectionsTypes)"""

    __tablename__ = "TAvanpostDirContactsMsgsDirectionsTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirContactsMsgsDirectionsTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)


class AvanpostDirContactMsgTypeModel(BaseModel):
    """Типы сообщений (TRSDirAppMsgsTypes)"""

    __tablename__ = "TAvanpostDirContactsMsgsTypes"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Direction", "FID", name="PK_AvanpostDirContactsMsgsTypes"),
        ForeignKeyConstraint(
            ["FK_Direction"],
            ["TAvanpostDirContactsMsgsDirectionsTypes.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ContactsMsgsTypes_Dir",
        ),
    )

    FK_Direction: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)


class AvanpostDirContactMsgProcessTypeModel(BaseModel):
    """Типы обработки сообщений (TRSDirAppContactsMsgsProcessTypes)"""

    __tablename__ = "TAvanpostDirContactsMsgsProcessTypes"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Direction", "FID", name="PK_AvanpostDirContactsMsgsProcessTypes"),
        ForeignKeyConstraint(
            ["FK_Direction"],
            ["TAvanpostDirContactsMsgsDirectionsTypes.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ContactsMsgsProcTypes_Dir",
        ),
    )

    FK_Direction: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FOrderBy: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostDirUserStatusTypeModel(BaseModel):
    """Статусы пользователей (TRSDirAppUsersStatusTypes)"""

    __tablename__ = "TAvanpostDirUsersStatusTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirUsersStatusTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FOrderBy: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostDirUserContactRoleTypeModel(BaseModel):
    """Роли контактов пользователей (TRSDirAppContactsLinksRoles)"""

    __tablename__ = "TAvanpostDirUsersContactsRolesTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirUsersContactsRolesTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)


class AvanpostDirUserLinkContactMsgControlProcessTypeModel(BaseModel):
    """Статусы обработки контрольных сообщений"""

    __tablename__ = "TAvanpostDirUsersLinksContactsMsgsControlsProcessTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_Avp_UsersLinksContactsMsgsCtrlProcTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)


class AvanpostDirScenarioGroupItemTypeModel(BaseModel):
    """Типы меню действий (TRSDirAppScenariosGroupsItemsTypes)"""

    __tablename__ = "TAvanpostDirScenariosGroupsItemsTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosGroupsItemsTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FComment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    FFlagDefault: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagLinkScenario: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagLinkScenarioGroup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagLinkScenarioInstruction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagLinkSubItems: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostDirScenarioTypeModel(BaseModel):
    """Типы сценариев действий (TRSDirAppScenariosTypes)"""

    __tablename__ = "TAvanpostDirScenariosTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FOrderBy: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FFlagCustom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostDirScenarioActionTypeModel(BaseModel):
    """Типы элементов сценариев действий (TRSDirAppScenariosActionsTypes)"""

    __tablename__ = "TAvanpostDirScenariosActionsTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosActionsTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FComment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    FOrderBy: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FFlagEditing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagGroup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagGroupItem: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostDirScenarioActionValueTypeModel(BaseModel):
    """Типы значений элементов сценариев действий"""

    __tablename__ = "TAvanpostDirScenariosActionsValuesTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosActionsValuesTypes"),)

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(255), nullable=False)
    FDataType: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FDataDefault: Mapped[str] = mapped_column(String(4000), nullable=True)


class AvanpostDirScenarioModel(BaseModel):
    """Сценарии действий (TRSAppScenarios)"""

    __tablename__ = "TAvanpostDirScenarios"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenarios"),
        ForeignKeyConstraint(
            ["FK_Type"], ["TAvanpostDirScenariosTypes.FID"], ondelete="RESTRICT", name="FK_Avp_Scenarios_Type"
        ),
    )

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)
    FFlagDefault: Mapped[bool] = mapped_column(Boolean, default=False)


class AvanpostDirScenarioActionModel(BaseModel):
    """Элементы сценариев действий (TRSAppScenariosActions)"""

    __tablename__ = "TAvanpostDirScenariosActions"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosActions"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostDirScenarios.FID"], ondelete="CASCADE", name="FK_Avp_ScenariosActions_Parent"
        ),
        ForeignKeyConstraint(
            ["FK_ParentItem"],
            ["TAvanpostDirScenariosActions.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ScenariosActions_ParentItem",
        ),
        ForeignKeyConstraint(
            ["FK_Type"],
            ["TAvanpostDirScenariosActionsTypes.FID"],
            ondelete="RESTRICT",
            name="FK_Avp_ScenariosActions_Type",
        ),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Parent: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_ParentItem: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FPosition: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class AvanpostDirScenarioActionLangModel(BaseModel):
    """Переводы элементов сценариев действий (TRSAppScenariosActionsLangs)"""

    __tablename__ = "TAvanpostDirScenariosActionsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_AvanpostDirScenariosActionsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosActions.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosActionsLangs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"],
            ["TAvanpostDirLanguages.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosActionsLangs_Lang",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)


class AvanpostDirScenarioActionValueModel(BaseModel):
    """Значения элементов действий (TRSAppScenariosActionsValues)"""

    __tablename__ = "TAvanpostDirScenariosActionsValues"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_AvanpostDirScenariosActionsValues"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosActions.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosActionsVals_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostDirScenariosActionsValuesTypes.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosActionsVals_Link",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class AvanpostDirScenarioInstructionModel(BaseModel):
    """Инструкции сценариев действий (TRSAppScenariosInstructions)"""

    __tablename__ = "TAvanpostDirScenariosInstructions"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosInstructions"),
        ForeignKeyConstraint(
            ["FK_Scenario"],
            ["TAvanpostDirScenarios.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosInstructions_Scenario",
        ),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Scenario: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class AvanpostDirScenarioInstructionFileModel(BaseModel):
    """Файлы инструкций сценариев действий (TRSAppScenariosInstructionsFiles)"""

    __tablename__ = "TAvanpostDirScenariosInstructionsFiles"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", "FK_Link", name="PK_Avp_ScenariosInstructionsFiles"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosInstructions.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosInstructionsFiles_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"],
            ["TAvanpostDirLanguages.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosInstructionsFiles_Lang",
        ),
        ForeignKeyConstraint(
            ["FK_Link"], ["TAvanpostFiles.FID"], ondelete="CASCADE", name="FK_Avp_ScenariosInstructionsFiles_Link"
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FK_Link: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class AvanpostDirScenarioInstructionLangModel(BaseModel):
    """Переводы файлов инструкций сценариев действий"""

    __tablename__ = "TAvanpostDirScenariosInstructionsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_Avp_ScenariosInstructionsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosInstructions.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosInstructionsLangs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"],
            ["TAvanpostDirLanguages.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosInstructionsLangs_Lang",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)


class AvanpostDirScenarioCustomModel(BaseModel):
    """Индивидуальные сценарии действий (TRSAppScenariosCustom)"""

    __tablename__ = "TAvanpostDirScenariosCustom"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_AvanpostDirScenariosCustom"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostDirScenarios.FID"], ondelete="CASCADE", name="FK_Avp_ScenariosCustom_Parent"
        ),
        ForeignKeyConstraint(
            ["FK_Link"], ["TAvanpostDirScenariosTypes.FID"], ondelete="CASCADE", name="FK_Avp_ScenariosCustom_Link"
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class AvanpostDirScenarioGroupModel(BaseModel):
    """Список меню действий (TRSAppScenariosGroups)"""

    __tablename__ = "TAvanpostDirScenariosGroups"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirScenariosGroups"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)

    items: Mapped[list["AvanpostDirScenarioGroupItemModel"]] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        back_populates="scenario_group",
        cascade="all, delete-orphan",
        foreign_keys="AvanpostDirScenarioGroupItemModel.FK_ScenarioGroup",
        primaryjoin="AvanpostDirScenarioGroupModel.FID == AvanpostDirScenarioGroupItemModel.FK_ScenarioGroup",
    )


class AvanpostDirScenarioGroupItemModel(BaseModel):
    """Меню действий (TRSAppScenariosGroupsItems)"""

    __tablename__ = "TAvanpostDirScenariosGroupsItems"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_Avp_ScenariosGroupsItems"),
        ForeignKeyConstraint(
            ["FK_ScenarioGroup"],
            ["TAvanpostDirScenariosGroups.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItems_Group",
        ),
        ForeignKeyConstraint(
            ["FK_ParentItem"],
            ["TAvanpostDirScenariosGroupsItems.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ScenariosGroupsItems_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Type"],
            ["TAvanpostDirScenariosGroupsItemsTypes.FID"],
            ondelete="RESTRICT",
            name="FK_Avp_ScenariosGroupsItems_Type",
        ),
        ForeignKeyConstraint(
            ["FK_Image"], ["TAvanpostFiles.FID"], ondelete="SET NULL", name="FK_Avp_ScenariosGroupsItems_Image"
        ),
        Index("IX_Avp_ScenariosGroupsItems_Group", "FK_ScenarioGroup"),
        Index("IX_Avp_ScenariosGroupsItems_Parent", "FK_ParentItem"),
        Index("IX_Avp_ScenariosGroupsItems_Level", "FLevel"),
        Index("IX_Avp_ScenariosGroupsItems_Position", "FPosition"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_ScenarioGroup: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_ParentItem: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_Image: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    FCode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    FLevel: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FPosition: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Связи
    scenario_group: Mapped["AvanpostDirScenarioGroupModel"] = relationship(
        "AvanpostDirScenarioGroupModel",
        back_populates="items",
        foreign_keys=[FK_ScenarioGroup],
        primaryjoin="AvanpostDirScenarioGroupItemModel.FK_ScenarioGroup == AvanpostDirScenarioGroupModel.FID",
    )

    parent_item: Mapped[Optional["AvanpostDirScenarioGroupItemModel"]] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        remote_side=[FID],
        foreign_keys=[FK_ParentItem],
        primaryjoin="AvanpostDirScenarioGroupItemModel.FID == AvanpostDirScenarioGroupItemModel.FK_ParentItem",
        uselist=False,
        overlaps="child_items",
    )

    child_items: Mapped[list["AvanpostDirScenarioGroupItemModel"]] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        remote_side=[FK_ParentItem],
        foreign_keys=[FK_ParentItem],
        primaryjoin="AvanpostDirScenarioGroupItemModel.FK_ParentItem == AvanpostDirScenarioGroupItemModel.FID",
        uselist=True,
        overlaps="parent_item",
    )

    langs: Mapped[list["AvanpostDirScenarioGroupItemLangModel"]] = relationship(
        "AvanpostDirScenarioGroupItemLangModel",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys="AvanpostDirScenarioGroupItemLangModel.FK_Parent",
        primaryjoin="AvanpostDirScenarioGroupItemModel.FID == AvanpostDirScenarioGroupItemLangModel.FK_Parent",
    )

    links_scenarios: Mapped[list["AvanpostDirScenarioGroupItemLinkScenarioModel"]] = relationship(
        "AvanpostDirScenarioGroupItemLinkScenarioModel",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys="AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent",
        primaryjoin="AvanpostDirScenarioGroupItemModel.FID == AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent",
    )

    links_scenario_groups: Mapped[list["AvanpostDirScenarioGroupItemLinkScenarioGroupModel"]] = relationship(
        "AvanpostDirScenarioGroupItemLinkScenarioGroupModel",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys="AvanpostDirScenarioGroupItemLinkScenarioGroupModel.FK_Parent",
        primaryjoin="AvanpostDirScenarioGroupItemModel.FID == AvanpostDirScenarioGroupItemLinkScenarioGroupModel.FK_Parent",
    )

    links_instructions: Mapped[list["AvanpostDirScenarioGroupItemLinkScenarioInstructionModel"]] = relationship(
        "AvanpostDirScenarioGroupItemLinkScenarioInstructionModel",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys="AvanpostDirScenarioGroupItemLinkScenarioInstructionModel.FK_Parent",
        primaryjoin="AvanpostDirScenarioGroupItemModel.FID == AvanpostDirScenarioGroupItemLinkScenarioInstructionModel.FK_Parent",
    )

    def __repr__(self) -> str:
        return f"<AvanpostDirScenarioGroupItemModel(id={self.FID}, name={self.get_name()})>"

    def get_name(self, lang_code: str = "ru") -> str:
        """Получение названия на указанном языке"""
        for lang in self.langs:
            if lang.FK_Lang == lang_code:
                return lang.FName or f"Item {self.FID}"
        return f"Item {self.FID}"

    @property
    def display_name(self) -> str:
        """Отображаемое имя (для совместимости с предыдущей моделью)"""
        return self.get_name()

    @property
    def has_subitems(self) -> bool:
        """Есть ли дочерние элементы"""
        return bool(self.child_items)

    @property
    def is_folder(self) -> bool:
        """Является ли папкой"""
        return bool(self.child_items)

    def to_dict(self, include_children: bool = False) -> dict[str, Any]:
        """Преобразование в словарь с поддержкой вложенности"""
        data: dict[str, Any] = {
            "id": self.FID,
            "name": self.get_name(),
            "display_name": self.display_name,
            "has_subitems": self.has_subitems,
            "level": self.FLevel,
            "code": self.FCode,
            "position": self.FPosition,
        }

        if include_children and self.child_items:
            data["children"] = [child.to_dict(include_children=False) for child in self.child_items]

        return data

    def to_telegram_dict(self) -> dict[str, Any]:
        """Преобразование для Telegram бота"""
        return {
            "id": self.FID,
            "name": self.get_name(),
            "display_name": self.display_name,
            "has_subitems": self.has_subitems,
        }


class AvanpostDirScenarioGroupItemLangModel(BaseModel):
    """Переводы меню действий (TRSAppScenariosGroupsItemsLangs)"""

    __tablename__ = "TAvanpostDirScenariosGroupsItemsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_Avp_ScenariosGroupsItemsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosGroupsItems.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItemsLangs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"], ["TAvanpostDirLanguages.FID"], ondelete="CASCADE", name="FK_Avp_ScenariosGroupsItemsLangs_Lang"
        ),
        Index("IX_Avp_ScenariosGroupsItemsLangs_Parent", "FK_Parent"),
        Index("IX_Avp_ScenariosGroupsItemsLangs_Lang", "FK_Lang"),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)

    parent: Mapped["AvanpostDirScenarioGroupItemModel"] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        back_populates="langs",
        foreign_keys=[FK_Parent],
        primaryjoin="AvanpostDirScenarioGroupItemLangModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID",
    )


class AvanpostDirScenarioGroupItemLinkScenarioModel(BaseModel):
    """Связь меню действий со сценариями действий"""

    __tablename__ = "TAvanpostDirScenariosGroupsItemsLinksScenarios"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_Avp_ScenariosGroupsItemsLinkScenarios"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosGroupsItems.FID"],
            ondelete="CASCADE",
            name="FK_Avp_SScenariosGroupsItemsLinkScenarios_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostDirScenarios.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItemsLinkSScenarios_Link",
        ),
        Index("IX_Avp_ScenariosGroupsItemsLinkScenarios_Parent", "FK_Parent"),
        Index("IX_Avp_ScenariosGroupsItemsLinkScenarios_Link", "FK_Link"),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    parent: Mapped["AvanpostDirScenarioGroupItemModel"] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        back_populates="links_scenarios",
        foreign_keys=[FK_Parent],
        primaryjoin="AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID",
    )


class AvanpostDirScenarioGroupItemLinkScenarioGroupModel(BaseModel):
    """Связь меню действий с группами подменю"""

    __tablename__ = "TAvanpostDirScenariosGroupsItemsLinksScenariosGroups"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_Avp_SScenariosGroupsItemsLinkScenariosGrp"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosGroupsItems.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItemsLinkScenariosGrp_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostDirScenariosGroups.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItemsLinkScenariosGrp_Link",
        ),
        Index("IX_Avp_ScenariosGroupsItemsLinkScenariosGrp_Parent", "FK_Parent"),
        Index("IX_Avp_ScenariosGroupsItemsLinkScenariosGrp_Link", "FK_Link"),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    parent: Mapped["AvanpostDirScenarioGroupItemModel"] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        back_populates="links_scenario_groups",
        foreign_keys=[FK_Parent],
        primaryjoin="AvanpostDirScenarioGroupItemLinkScenarioGroupModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID",
    )


class AvanpostDirScenarioGroupItemLinkScenarioInstructionModel(BaseModel):
    """Связь меню действий с инструкцией"""

    __tablename__ = "TAvanpostDirScenariosGroupsItemsLinksScenariosInstructions"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_Avp_ScenariosGroupsItemsLinkInstr"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostDirScenariosGroupsItems.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItemsLinkInstr_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostDirScenariosInstructions.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ScenariosGroupsItemsLinkInstr_Link",
        ),
        Index("IX_Avp_ScenariosGroupsItemsLinkInstr_Parent", "FK_Parent"),
        Index("IX_Avp_ScenariosGroupsItemsLinkInstr_Link", "FK_Link"),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    parent: Mapped["AvanpostDirScenarioGroupItemModel"] = relationship(
        "AvanpostDirScenarioGroupItemModel",
        back_populates="links_instructions",
        foreign_keys=[FK_Parent],
        primaryjoin="AvanpostDirScenarioGroupItemLinkScenarioInstructionModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID",
    )


# ============ МОДЕЛИ ДАННЫХ ============


class AvanpostContactModel(BaseModel):
    """Контактные лица (TRSAppContacts)"""

    __tablename__ = "TAvanpostContacts"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostContacts"),
        Index("IX_AvanpostContacts_Group", "FK_Group"),
    )

    FID: Mapped[int] = mapped_column(Integer, primary_key=True)
    FK_Group: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class AvanpostContactLangModel(BaseModel):
    """Переводы контактных лиц (TRSAppContactsLangs)"""

    __tablename__ = "TAvanpostContactsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_AvanpostContactsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostContacts.FID"], ondelete="CASCADE", name="FK_AvanpostContactsLangs_Parent"
        ),
        ForeignKeyConstraint(
            ["FK_Lang"], ["TAvanpostDirLanguages.FID"], ondelete="CASCADE", name="FK_AvanpostContactsLangs_Lang"
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)


class AvanpostContactLinkModel(BaseModel):
    """Контакты контактных лиц (TRSAppContactsLinks)"""

    __tablename__ = "TAvanpostContactsLinks"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostContactsLinks"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostContacts.FID"],
            ondelete="CASCADE",
            name="FK_Avp_ContactsLinks_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Owner"],
            ["TAvanpostDirOwners.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ContactsLinks_Owner",
        ),
        ForeignKeyConstraint(
            ["FK_Type"],
            ["TAvanpostDirContactsLinksTypes.FID"],
            ondelete="RESTRICT",
            name="FK_Avp_ContactsLinks_Type",
        ),
        ForeignKeyConstraint(
            ["FK_Operator"],
            ["TAvanpostDirOperators.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ContactsLinks_Operator",
        ),
        Index("IX_AvanpostContactsLinks_Parent", "FK_Parent"),
        Index("IX_AvanpostContactsLinks_Contact", "FContact"),
    )

    FID: Mapped[int] = mapped_column(Integer, primary_key=True)
    FK_Parent: Mapped[int] = mapped_column(Integer, nullable=True)
    FK_Owner: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_Operator: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, server_default=None)
    FContact: Mapped[str] = mapped_column(String(50), nullable=False)
    FOrderBy: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostUserModel(BaseModel):
    """Пользователи (TRSAppUsers)"""

    __tablename__ = "TAvanpostUsers"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsers"),
        ForeignKeyConstraint(
            ["FK_MenuGroup"], ["TAvanpostDirScenariosGroups.FID"], ondelete="SET NULL", name="FK_Avp_Users_MenuGroup"
        ),
        ForeignKeyConstraint(
            ["FK_Group"], ["TAvanpostDirContactsGroups.FID"], ondelete="RESTRICT", name="FK_Avp_Users_Group"
        ),
        ForeignKeyConstraint(
            ["FK_Contact"], ["TAvanpostContacts.FID"], ondelete="RESTRICT", name="FK_Avp_Users_Contact"
        ),
        ForeignKeyConstraint(["FK_Owner"], ["TAvanpostDirOwners.FID"], ondelete="SET NULL", name="FK_Avp_Users_Owner"),
        ForeignKeyConstraint(
            ["FK_MotorCade"], ["TAvanpostDirOwnersMotorCades.FID"], ondelete="SET NULL", name="FK_Avp_Users_MotorCade"
        ),
        ForeignKeyConstraint(
            ["FK_Language"], ["TAvanpostDirLanguages.FID"], ondelete="RESTRICT", name="FK_Avp_Users_Lang"
        ),
        Index("IX_AvanpostUsers_Contact", "FK_Contact"),
        Index("IX_AvanpostUsers_MenuGroup", "FK_MenuGroup"),
        Index("IX_AvanpostUsers_Phone", "FPhone"),
    )

    FID: Mapped[int] = mapped_column(Integer, primary_key=True)
    FK_MenuGroup: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FK_Group: Mapped[int] = mapped_column(SmallInteger, nullable=True)
    FK_Contact: Mapped[int] = mapped_column(Integer, nullable=True)
    FK_Owner: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FK_MotorCade: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Language: Mapped[str] = mapped_column(CHAR(2), nullable=True)
    FName: Mapped[str | None] = mapped_column(String(50), nullable=True)
    FPhone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    user_link: Mapped[Optional["AvanpostUserLinkModel"]] = relationship(
        "AvanpostUserLinkModel",
        foreign_keys="AvanpostUserLinkModel.FK_Parent",
        back_populates="avanpost_user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def fk_user(self) -> int | None:
        """Получение FK_Link из связанной модели"""
        return self.user_link.FK_Link if self.user_link else None

    @fk_user.setter
    def fk_user(self, value: int | None) -> None:
        """Установка FK_Link в связанную модель"""
        if not self.user_link:
            self.user_link = AvanpostUserLinkModel(FK_Parent=self.FID)
        self.user_link.FK_Link = value


class AvanpostUserLinkModel(BaseModel):
    """Связь пользователя Avanpost с Telegram пользователем"""

    __tablename__ = "TAvanpostUsersLinks"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", name="PK_AvanpostUsersLinks"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersLinks_Parent"
        ),
        ForeignKeyConstraint(["FK_Link"], ["TUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersLinks_Link"),
    )

    FK_Parent: Mapped[int] = mapped_column(Integer, primary_key=True)
    FK_Link: Mapped[int | None] = mapped_column(Integer, nullable=True)

    avanpost_user: Mapped["AvanpostUserModel"] = relationship(
        "AvanpostUserModel",
        foreign_keys=[FK_Parent],
        back_populates="user_link",
        uselist=False,
    )

    telegram_user: Mapped[Optional["UserModel"]] = relationship(
        "UserModel",
        foreign_keys=[FK_Link],
        back_populates="avanpost_link",
        uselist=False,
    )


class AvanpostUserChatModel(BaseModel):
    """Чаты пользователей (TRSAppUsersObjectsChats)"""

    __tablename__ = "TAvanpostUsersChats"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsersChats"),
        ForeignKeyConstraint(["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersChats_User"),
        ForeignKeyConstraint(
            ["FK_Owner"], ["TAvanpostContacts.FID"], ondelete="RESTRICT", name="FK_Avp_UsersChats_Owner"
        ),
        Index("IX_AvanpostUsersChats_User", "FK_User"),
        Index("IX_AvanpostUsersChats_Owner", "FK_Owner"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int] = mapped_column(Integer, nullable=False)
    FK_Owner: Mapped[int] = mapped_column(Integer, nullable=False)
    FFlagPrimary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostUserChatLangModel(BaseModel):
    """Переводы чатов пользователей (TRSAppUsersObjectsChatsLangs)"""

    __tablename__ = "TAvanpostUsersChatsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_AvanpostUsersChatsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostUsersChats.FID"], ondelete="CASCADE", name="FK_AvanpostUsersChatsLangs_Parent"
        ),
        ForeignKeyConstraint(
            ["FK_Lang"], ["TAvanpostDirLanguages.FID"], ondelete="CASCADE", name="FK_AvanpostUsersChatsLangs_Lang"
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)


# ============ ОСТАЛЬНЫЕ МОДЕЛИ ============


class AvanpostMsgModel(BaseModel):
    """Сообщения (TRSAppMsgs)"""

    __tablename__ = "TAvanpostMsgs"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostMsgs"),)

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FText: Mapped[str | None] = mapped_column(Text, nullable=True)
    FSize: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AvanpostContactMsgModel(BaseModel):
    """Сообщения контактов (TRSAppContactsMsgs)"""

    __tablename__ = "TAvanpostContactsMsgs"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostContactsMsgs"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostContacts.FID"], ondelete="CASCADE", name="FK_Avp_ContactsMsgs_Parent"
        ),
        ForeignKeyConstraint(["FK_Link"], ["TAvanpostMsgs.FID"], ondelete="CASCADE", name="FK_Avp_ContactsMsgs_Link"),
        ForeignKeyConstraint(
            ["FK_Direction", "FK_Type"],
            ["TAvanpostDirContactsMsgsTypes.FK_Direction", "TAvanpostDirContactsMsgsTypes.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ContactsMsgs_Type",
        ),
        ForeignKeyConstraint(
            ["FK_ContactAuthor"], ["TAvanpostContacts.FID"], ondelete="SET NULL", name="FK_Avp_ContactsMsgs_Author"
        ),
        ForeignKeyConstraint(
            ["FK_ContactTarget"], ["TAvanpostContacts.FID"], ondelete="SET NULL", name="FK_Avp_ContactsMsgs_Target"
        ),
        Index("IX_AvanpostContactsMsgs_Parent", "FK_Parent"),
        Index("IX_AvanpostContactsMsgs_Link", "FK_Link"),
        Index("IX_AvanpostContactsMsgs_Date", "FDate"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Parent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FK_Source: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Link: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Direction: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_ContactAuthor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FK_ContactTarget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FDate: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AvanpostContactMsgProcessModel(BaseModel):
    """Обработки сообщений контактов (TRSAppContactsMsgsProcess)"""

    __tablename__ = "TAvanpostContactsMsgsProcess"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostContactsMsgsProcess"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostContactsMsgs.FID"], ondelete="CASCADE", name="FK_Avp_ContactsMsgsProc_Parent"
        ),
        ForeignKeyConstraint(
            ["FK_ContactLinkSource"],
            ["TAvanpostContactsLinks.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ContactsMsgsProc_LinkSrc",
        ),
        ForeignKeyConstraint(
            ["FK_Direction", "FK_ProcessType"],
            ["TAvanpostDirContactsMsgsProcessTypes.FK_Direction", "TAvanpostDirContactsMsgsProcessTypes.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ContactsMsgsProc_ProcessType",
        ),
        ForeignKeyConstraint(
            ["FK_ContactProcess"],
            ["TAvanpostContacts.FID"],
            ondelete="SET NULL",
            name="FK_Avp_ContactsMsgsProc_ContactProc",
        ),
        Index("IX_AvanpostContactsMsgsProcess_Parent", "FK_Parent"),
        Index("IX_AvanpostContactsMsgsProcess_DateProcess", "FDateProcess"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Parent: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_Direction: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_ProcessType: Mapped[int | None] = mapped_column(SmallInteger, nullable=False)
    FK_ContactLinkSource: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FK_ContactProcess: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FDate: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDateSend: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDateDelivery: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDateProcess: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FFlagPrimary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostUserStatusModel(BaseModel):
    """Статус пользователя (TRSAppUsersStatus)"""

    __tablename__ = "TAvanpostUsersStatus"
    __table_args__ = (
        PrimaryKeyConstraint("FK_User", name="PK_AvanpostUsersStatus"),
        ForeignKeyConstraint(["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersStatus_User"),
        ForeignKeyConstraint(
            ["FK_Status"], ["TAvanpostDirUsersStatusTypes.FID"], ondelete="RESTRICT", name="FK_Avp_UsersStatus_Status"
        ),
    )

    FK_User: Mapped[int] = mapped_column(Integer, primary_key=True)
    FK_Status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FComment: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AvanpostUserLinkContactModel(BaseModel):
    """Связь пользователей и контактов (TRSAppUsersObjectsContacts)"""

    __tablename__ = "TAvanpostUsersLinksContacts"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsersLinksContacts"),
        ForeignKeyConstraint(
            ["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersLinksContacts_User"
        ),
        ForeignKeyConstraint(
            ["FK_Role"],
            ["TAvanpostDirUsersContactsRolesTypes.FID"],
            ondelete="RESTRICT",
            name="FK_Avp_UsersLinksContacts_Role",
        ),
        ForeignKeyConstraint(
            ["FK_Link"], ["TAvanpostContacts.FID"], ondelete="CASCADE", name="FK_Avp_UsersLinksContacts_Link"
        ),
        Index("IX_AvanpostUsersLinksContacts_User", "FK_User"),
        Index("IX_AvanpostUsersLinksContacts_Link", "FK_Link"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int] = mapped_column(Integer, nullable=False)
    FK_Role: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FK_Link: Mapped[int] = mapped_column(Integer, nullable=False)


class AvanpostUserMissionModel(BaseModel):
    """Задания пользователей (TRSAppUsersObjectsMissions)"""

    __tablename__ = "TAvanpostUsersMissions"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsersMissions"),
        ForeignKeyConstraint(["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersMissions_User"),
        Index("IX_AvanpostUsersMissions_User", "FK_User"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int] = mapped_column(Integer, nullable=False)
    FFlagCurrent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagNext: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AvanpostUserMissionLangModel(BaseModel):
    """Переводы контактных лиц (TRSAppUsersObjectsMissionsLangs)"""

    __tablename__ = "TAvanpostUsersMissionsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_AvanpostUsersMissionsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostUsersMissions.FID"],
            ondelete="CASCADE",
            name="FK_AvanpostUsersMissionsLangs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"], ["TAvanpostDirLanguages.FID"], ondelete="CASCADE", name="FK_AvanpostUsersMissionsLangs_Lang"
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str] = mapped_column(String(128), nullable=False)
    FInfo: Mapped[str | None] = mapped_column(String(4000), nullable=True)


class AvanpostUserMissionItemModel(BaseModel):
    """Точки заданий пользователей (TRSAppUsersObjectsMissionsItems)"""

    __tablename__ = "TAvanpostUsersMissionsItems"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsersMissionsItems"),
        ForeignKeyConstraint(["FK_User"], ["TAvanpostUsers.FID"], name="FK_Avp_sersMissionsItems_User"),
        ForeignKeyConstraint(
            ["FK_Mission"], ["TAvanpostUsersMissions.FID"], ondelete="CASCADE", name="FK_Avp_UsersMissionsItems_Mission"
        ),
        ForeignKeyConstraint(
            ["FK_ScenarioGroup"], ["TAvanpostDirScenariosGroups.FID"], name="FK_Avp_UsersMissionsItems_ScenarioGroup"
        ),
        Index("IX_AvanpostUsersMissionsItems_Mission", "FK_Mission"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Mission: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FK_ScenarioGroup: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FPosition: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostUserMissionItemLangModel(BaseModel):
    """Переводы контактных лиц (TRSAppUsersObjectsMissionsItemsLangs)"""

    __tablename__ = "TAvanpostUsersMissionsItemsLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_AvanpostUsersMissionsItemsLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostUsersMissionsItems.FID"],
            ondelete="CASCADE",
            name="FK_AvanpostUsersMissionsItemsLangs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"],
            ["TAvanpostDirLanguages.FID"],
            ondelete="CASCADE",
            name="FK_AvanpostUsersMissionsItemsLangs_Lang",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str | None] = mapped_column(String(100), nullable=True)
    FDescription: Mapped[str | None] = mapped_column(Text, nullable=True)


class AvanpostUserOrderModel(BaseModel):
    """Заказы пользователей (TRSAppUsersObjectsOrders)"""

    __tablename__ = "TAvanpostUsersOrders"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsersOrders"),
        ForeignKeyConstraint(["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersOrders_User"),
        Index("IX_AvanpostUsersOrders_User", "FK_User"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int] = mapped_column(Integer, nullable=False)
    FName: Mapped[str] = mapped_column(String(100), nullable=False)
    FInfo: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    FPosition: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostUserOrderLangModel(BaseModel):
    """Переводы заказов пользователей (TRSAppUsersObjectsOrdersLangs)"""

    __tablename__ = "TAvanpostUsersOrdersLangs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Lang", name="PK_AvanpostUsersOrdersLangs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostUsersOrders.FID"],
            ondelete="CASCADE",
            name="FK_AvanpostUsersOrdersLangs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Lang"],
            ["TAvanpostDirLanguages.FID"],
            ondelete="CASCADE",
            name="FK_AvanpostUsersOrdersLangs_Lang",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Lang: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    FName: Mapped[str | None] = mapped_column(String(100), nullable=True)
    FInfo: Mapped[str | None] = mapped_column(String(4000), nullable=True)


class AvanpostUserOrderLinkMissionModel(BaseModel):
    """Связь заказов пользователей и заданий (TRSAppUsersObjectsLinksMissions)"""

    __tablename__ = "TAvanpostUsersLinksContactsMissions"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_Avp_UsersLinksContactsMissions"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostUsersOrders.FID"],
            ondelete="CASCADE",
            name="FK_Avp_UsersLinksContactsMissions_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostUsersMissions.FID"],
            ondelete="CASCADE",
            name="FK_Avp_UsersLinksContactsMissions_Link",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class AvanpostUserVehicleModel(BaseModel):
    """Транспорт пользователей (TRSAppUsersObjectsVehicles)"""

    __tablename__ = "TAvanpostUsersVehicles"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostUsersVehicles"),
        ForeignKeyConstraint(["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersVehicles_User"),
        ForeignKeyConstraint(
            ["FK_Contact"], ["TAvanpostContacts.FID"], ondelete="RESTRICT", name="FK_Avp_UsersVehicles_Contact"
        ),
        Index("IX_AvanpostUsersVehicles_User", "FK_User"),
        Index("IX_AvanpostUsersVehicles_Contact", "FK_Contact"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int] = mapped_column(Integer, nullable=False)
    FK_Contact: Mapped[int] = mapped_column(Integer, nullable=False)
    FPosition: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class AvanpostUserLinkChatContactMsgModel(BaseModel):
    """Связь чатов пользователей и сообщений контактов (TRSAppUsersObjectsChatsLinksMsgs)"""

    __tablename__ = "TAvanpostUsersLinksChatsContactsMsgs"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_Avp_UsersLinksChatsContactsMsgs"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostUsersChats.FID"],
            ondelete="CASCADE",
            name="FK_Avp_UsersLinksChatsContactsMsgs_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostContactsMsgs.FID"],
            ondelete="CASCADE",
            name="FK_Avp_UsersLinksChatsContactsMsgs_Link",
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class AvanpostUserLinkContactMsgControlModel(BaseModel):
    """Связь пользователей и контрольных сообщений контактов"""

    __tablename__ = "TAvanpostUsersLinksContactsMsgsControls"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_Avp_UsersLinksContactsMsgsControls"),
        ForeignKeyConstraint(
            ["FK_User"], ["TAvanpostUsers.FID"], ondelete="CASCADE", name="FK_Avp_UsersLinksContactsMsgsControls_User"
        ),
        ForeignKeyConstraint(
            ["FK_Link"],
            ["TAvanpostContactsMsgs.FID"],
            ondelete="CASCADE",
            name="FK_Avp_UsersLinksContactsMsgsControls_Link",
        ),
        ForeignKeyConstraint(
            ["FK_ProcessStatus"],
            ["TAvanpostDirUsersLinksContactsMsgsControlsProcessTypes.FID"],
            ondelete="SET NULL",
            name="FK_Avp_UsersLinksContactsMsgsControls_ProcStatus",
        ),
        Index("IX_Avp_UsersLinksContactsMsgsControls_User", "FK_User"),
        Index("IX_Avp_UsersLinksContactsMsgsControls_Link", "FK_Link"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_User: Mapped[int] = mapped_column(Integer, nullable=False)
    FK_Link: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_ProcessStatus: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    FFlagAlarm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagAccessEdit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FFlagAccessProcess: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ============ МОДЕЛИ ОТЛОЖЕННОЙ СИНХРОНИЗАЦИИ ============


class AvanpostFileModel(BaseModel):
    """Файлы (TRSAppFiles)"""

    __tablename__ = "TAvanpostFiles"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostFiles"),
        ForeignKeyConstraint(
            ["FK_Type"], ["TAvanpostDirFilesTypes.FID"], ondelete="RESTRICT", name="FK_Avp_Files_Type"
        ),
        Index("IX_AvanpostFiles_Type", "FK_Type"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    FName: Mapped[str] = mapped_column(String(64), nullable=False)
    FExtention: Mapped[str] = mapped_column(String(16), nullable=False)
    FSize: Mapped[int] = mapped_column(Integer, nullable=False)
    FDateReg: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AvanpostLinkMsgFileModel(BaseModel):
    """Связь сообщений и файлов (TRSAppMsgsFiles)"""

    __tablename__ = "TAvanpostLinksMsgsFiles"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_AvanpostLinksMsgsFiles"),
        ForeignKeyConstraint(
            ["FK_Parent"], ["TAvanpostMsgs.FID"], ondelete="CASCADE", name="FK_Avp_LinksMsgsFiles_Parent"
        ),
        ForeignKeyConstraint(
            ["FK_Link"], ["TAvanpostFiles.FID"], ondelete="CASCADE", name="FK_Avp_LinksMsgsFiles_Link"
        ),
        UniqueConstraint("FK_Parent", "FK_Link", name="UK_Avp_LinksMsgsFiles_Parent_Link"),
        Index("IX_AvanpostLinksMsgsFiles_Parent", "FK_Parent"),
        Index("IX_AvanpostLinksMsgsFiles_Link", "FK_Link"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Parent: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_Link: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AvanpostLinkContactMsgFileModel(BaseModel):
    """Связь сообщений контактов и файлов (TRSAppContactsMsgsFiles)"""

    __tablename__ = "TAvanpostLinksContactsMsgsFiles"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Parent", "FK_Link", name="PK_Avp_LinksContactsMsgsFiles"),
        ForeignKeyConstraint(
            ["FK_Parent"],
            ["TAvanpostContactsMsgs.FID"],
            ondelete="CASCADE",
            name="FK_Avp_LinksContactsMsgsFiles_Parent",
        ),
        ForeignKeyConstraint(
            ["FK_Link"], ["TAvanpostLinksMsgsFiles.FID"], ondelete="CASCADE", name="FK_Avp_LinksContactsMsgsFiles_Link"
        ),
    )

    FK_Parent: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Link: Mapped[int] = mapped_column(BigInteger, primary_key=True)


# ============ МОДЕЛИ СИСТЕМНЫХ ДАННЫХ ============


class AvanpostDirSysDataTypeModel(BaseModel):
    """Типы данных (TRSDirSysDataTypes)"""

    __tablename__ = "TAvanpostDirSysDataTypes"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_AvanpostDirSysDataTypes"),)

    FID: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FName: Mapped[str] = mapped_column(String(255), nullable=False)
    FUserRelated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FDeferredSync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    FTableName: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AvanpostSysUpdateModel(BaseModel):
    """Время синхронизации данных системы (TRSSysUpdates)"""

    __tablename__ = "TAvanpostSysUpdates"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Type", name="PK_AvanpostSysUpdates"),
        ForeignKeyConstraint(
            ["FK_Type"],
            ["TAvanpostDirSysDataTypes.FID"],
            ondelete="CASCADE",
            name="FK_Avp_SysUpdates_Type",
        ),
    )

    FK_Type: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FDate: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AvanpostSysUserUpdateModel(BaseModel):
    """Время синхронизации данных пользователей (TRSSysUsersUpdates)"""

    __tablename__ = "TAvanpostSysUsersUpdates"
    __table_args__ = (
        PrimaryKeyConstraint("FK_User", "FK_Type", name="PK_Avp_SysUsersUpdates"),
        ForeignKeyConstraint(
            ["FK_User"],
            ["TAvanpostUsers.FID"],
            ondelete="CASCADE",
            name="FK_Avp_SysUsersUpdates_User",
        ),
        ForeignKeyConstraint(
            ["FK_Type"],
            ["TAvanpostDirSysDataTypes.FID"],
            ondelete="CASCADE",
            name="FK_Avp_SysUsersUpdates_Type",
        ),
        Index("IX_AvanpostSysUsersUpdates_User", "FK_User"),
        Index("IX_AvanpostSysUsersUpdates_Type", "FK_Type"),
    )

    FK_User: Mapped[int] = mapped_column(Integer, primary_key=True)
    FK_Type: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    FDate: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ============ МАППИНГ ТИПОВ ДАННЫХ ДЛЯ СИНХРОНИЗАЦИИ ============

AVANPOST_MODEL_MAPPING: dict[int, Any] = {
    # Базовые справочники (ID 1-20)
    1: AvanpostDirLanguageModel,
    2: AvanpostDirContactGroupModel,
    3: AvanpostDirContactLinkTypeModel,
    4: AvanpostDirOperatorModel,
    5: AvanpostDirOwnerModel,
    6: AvanpostDirOwnerMotorCadeModel,
    7: AvanpostDirFileTypeModel,
    8: AvanpostDirContactMsgDirectionTypeModel,
    9: AvanpostDirContactMsgTypeModel,
    10: AvanpostDirContactMsgProcessTypeModel,
    11: AvanpostDirScenarioTypeModel,
    12: AvanpostDirScenarioGroupItemTypeModel,
    13: AvanpostDirUserStatusTypeModel,
    14: AvanpostDirUserContactRoleTypeModel,
    15: AvanpostDirUserLinkContactMsgControlProcessTypeModel,
    16: AvanpostDirScenarioActionTypeModel,
    17: AvanpostDirScenarioActionValueTypeModel,
    # Сценарии действий (ID 101-120)
    101: AvanpostDirScenarioModel,
    102: AvanpostDirScenarioActionModel,
    103: AvanpostDirScenarioActionLangModel,
    104: AvanpostDirScenarioActionValueModel,
    105: AvanpostDirScenarioInstructionModel,
    106: AvanpostDirScenarioInstructionLangModel,
    107: AvanpostDirScenarioCustomModel,
    108: AvanpostDirScenarioGroupModel,
    # Меню действий (ID 201-220)
    201: AvanpostDirScenarioGroupItemModel,
    202: AvanpostDirScenarioGroupItemLangModel,
    203: AvanpostDirScenarioGroupItemLinkScenarioModel,
    204: AvanpostDirScenarioGroupItemLinkScenarioGroupModel,
    205: AvanpostDirScenarioGroupItemLinkScenarioInstructionModel,
    # Данные (ID 301-320)
    301: AvanpostContactModel,
    302: AvanpostContactLangModel,
    303: AvanpostContactLinkModel,
    # Данные с пользователями (ID 401-420)
    401: AvanpostUserModel,
    402: AvanpostUserChatModel,
    403: AvanpostUserChatLangModel,
    # Оперативная синхронизация (ID 501-520)
    501: AvanpostUserStatusModel,
    502: AvanpostUserLinkContactModel,
    503: AvanpostUserMissionModel,
    504: AvanpostUserMissionLangModel,
    505: AvanpostUserMissionItemModel,
    506: AvanpostUserMissionItemLangModel,
    507: AvanpostUserOrderModel,
    508: AvanpostUserOrderLangModel,
    509: AvanpostUserOrderLinkMissionModel,
    510: AvanpostUserVehicleModel,
    # Медленная синхронизация (ID 601-620)
    601: AvanpostMsgModel,
    602: AvanpostContactMsgModel,
    603: AvanpostContactMsgProcessModel,
    604: AvanpostUserLinkChatContactMsgModel,
    605: AvanpostUserLinkContactMsgControlModel,
    # Отложенная синхронизация (ID 701-720)
    701: AvanpostFileModel,
    702: AvanpostLinkMsgFileModel,
    703: AvanpostLinkContactMsgFileModel,
    704: AvanpostDirScenarioInstructionFileModel,
}


def get_avanpost_model(data_type_id: int) -> Any:
    """Получение модели по типу данных."""
    return AVANPOST_MODEL_MAPPING.get(data_type_id)


def get_avanpost_table_name(data_type_id: int) -> str | None:
    """Получение имени таблицы по типу данных."""
    model = get_avanpost_model(data_type_id)
    return model.__tablename__ if model else None


# ============ КОНСТАНТЫ ТИПОВ ДАННЫХ ДЛЯ СИНХРОНИЗАЦИИ ============

AVANPOST_BASE_DATA_TYPES: list[int] = (
    list(range(1, 18)) + list(range(101, 109)) + list(range(201, 206)) + list(range(301, 304))
)

AVANPOST_USER_DATA_TYPES: list[int] = [
    401,  # Пользователи
    402,  # Чаты
    403,  # Переводы чатов
    501,  # Статусы пользователей
    502,  # Связи пользователей с контактами
    503,  # Задания
    504,  # Переводы заданий
    505,  # Пункты заданий
    506,  # Переводы пунктов
    507,  # Заказы
    508,  # Переводы заказов
    509,  # Связи заказов с заданиями
    510,  # Транспорт
    601,  # Сообщения
    602,  # Сообщения контактов
    603,  # Обработки сообщений контактов
    604,  # Связи чатов пользователей с сообщениями контактов
    605,  # Связи пользователей с контрольными сообщениями
]

# ============ ЭКСПОРТ ============

__all__ = [
    # Базовые справочники
    "AvanpostDirLanguageModel",
    "AvanpostDirContactGroupModel",
    "AvanpostDirContactLinkTypeModel",
    "AvanpostDirOperatorModel",
    "AvanpostDirOwnerModel",
    "AvanpostDirOwnerMotorCadeModel",
    "AvanpostDirFileTypeModel",
    "AvanpostDirContactMsgDirectionTypeModel",
    "AvanpostDirContactMsgTypeModel",
    "AvanpostDirContactMsgProcessTypeModel",
    "AvanpostDirUserStatusTypeModel",
    "AvanpostDirUserContactRoleTypeModel",
    "AvanpostDirUserLinkContactMsgControlProcessTypeModel",
    "AvanpostDirScenarioGroupItemTypeModel",
    "AvanpostDirScenarioTypeModel",
    "AvanpostDirScenarioActionTypeModel",
    "AvanpostDirScenarioActionValueTypeModel",
    # Сценарии действий
    "AvanpostDirScenarioModel",
    "AvanpostDirScenarioActionModel",
    "AvanpostDirScenarioActionLangModel",
    "AvanpostDirScenarioActionValueModel",
    "AvanpostDirScenarioInstructionModel",
    "AvanpostDirScenarioInstructionFileModel",
    "AvanpostDirScenarioInstructionLangModel",
    "AvanpostDirScenarioCustomModel",
    # Меню действий
    "AvanpostDirScenarioGroupModel",
    "AvanpostDirScenarioGroupItemModel",
    "AvanpostDirScenarioGroupItemLangModel",
    "AvanpostDirScenarioGroupItemLinkScenarioModel",
    "AvanpostDirScenarioGroupItemLinkScenarioGroupModel",
    "AvanpostDirScenarioGroupItemLinkScenarioInstructionModel",
    # Данные
    "AvanpostContactModel",
    "AvanpostContactLangModel",
    "AvanpostContactLinkModel",
    "AvanpostUserModel",
    "AvanpostUserLinkModel",
    "AvanpostUserChatModel",
    "AvanpostUserChatLangModel",
    # Оперативная синхронизация
    "AvanpostMsgModel",
    "AvanpostContactMsgModel",
    "AvanpostContactMsgProcessModel",
    "AvanpostUserStatusModel",
    "AvanpostUserLinkContactModel",
    "AvanpostUserMissionModel",
    "AvanpostUserMissionLangModel",
    "AvanpostUserMissionItemModel",
    "AvanpostUserMissionItemLangModel",
    "AvanpostUserOrderModel",
    "AvanpostUserOrderLangModel",
    "AvanpostUserOrderLinkMissionModel",
    "AvanpostUserVehicleModel",
    "AvanpostUserLinkChatContactMsgModel",
    "AvanpostUserLinkContactMsgControlModel",
    # Отложенная синхронизация
    "AvanpostFileModel",
    "AvanpostLinkMsgFileModel",
    "AvanpostLinkContactMsgFileModel",
    # Системные
    "AvanpostDirSysDataTypeModel",
    "AvanpostSysUpdateModel",
    "AvanpostSysUserUpdateModel",
    # Маппинг и константы
    "AVANPOST_MODEL_MAPPING",
    "get_avanpost_model",
    "get_avanpost_table_name",
    "AVANPOST_BASE_DATA_TYPES",
    "AVANPOST_USER_DATA_TYPES",
]
