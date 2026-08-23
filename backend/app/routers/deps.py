"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..auth import Owner, identify
from ..container import Studio, get_studio


def studio_dep(request: Request) -> Studio:
    return getattr(request.app.state, "studio", None) or get_studio()


StudioDep = Annotated[Studio, Depends(studio_dep)]


def owner_dep(request: Request, studio: StudioDep) -> Owner:
    return identify(request, studio.settings)


OwnerDep = Annotated[Owner, Depends(owner_dep)]
