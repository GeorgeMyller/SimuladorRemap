"""``grids.py`` (RF-10) e ``provenance.py`` (RF-06) com dados sintéticos."""

from __future__ import annotations

import pytest

from simremap.catalog.contracts import Provenance, ProvenanceKind, VehicleSpec
from simremap.catalog.grids import Grid1D, Grid2D, interp1d, interp2d, interp_linear
from simremap.catalog.loader import Catalog
from simremap.catalog.provenance import (
    effective_provenance,
    estimated_fields,
    invalid_provenance_pointers,
    resolve_pointer,
)


class TestGrids:
    def test_bilinear_reference_case(self) -> None:
        grid = Grid2D(x_name="rpm", x_values=[2000, 2500], y_name="map_kpa", y_values=[50, 100],
                      z_values=[[10, 20], [30, 40]])  # fmt: skip
        assert interp2d(grid, 2250, 75) == pytest.approx(25.0)
        assert interp2d(grid, 2000, 50) == 10.0
        assert interp2d(grid, 9000, 500) == 40.0  # saturação, sem extrapolação
        assert interp2d(grid, 0, 0) == 10.0

    def test_linear_1d(self) -> None:
        grid = Grid1D(x_name="pressure_ratio", x_values=[1.0, 2.0, 3.0], values=[0.5, 0.7, 0.6])
        assert interp1d(grid, 1.5) == pytest.approx(0.6)
        assert interp1d(grid, 2.5) == pytest.approx(0.65)
        assert interp1d(grid, 0.0) == 0.5
        assert interp1d(grid, 9.0) == 0.6

    def test_interp_linear_validation(self) -> None:
        with pytest.raises(ValueError, match="comprimento"):
            interp_linear([1.0], [1.0], 1.0)
        assert interp_linear([0.0, 10.0], [0.0, 100.0], 2.5) == 25.0

    def test_real_ve_corner(self, real_catalog: Catalog) -> None:
        ve = real_catalog.vehicles["hatch-20t-gdi"].spec.engine.true_ve
        assert interp2d(ve, ve.x_values[0], ve.y_values[0]) == ve.z_values[0][0]
        assert interp2d(ve, ve.x_values[-1], ve.y_values[-1]) == ve.z_values[-1][-1]


class TestProvenance:
    def test_ancestor_coverage(self) -> None:
        prov = {
            "/turbo": Provenance(kind=ProvenanceKind.ESTIMATE),
            "/turbo/housing": Provenance(kind=ProvenanceKind.PRD),
        }
        assert effective_provenance(prov, "/turbo/housing").kind == "prd"  # type: ignore[union-attr]
        assert effective_provenance(prov, "/turbo/compressor/eta_max").kind == "estimate"  # type: ignore[union-attr]
        assert effective_provenance(prov, "/engine/bore_mm") is None

    def test_parent_literature_covers_children(self, real_catalog: Catalog) -> None:
        spec = real_catalog.vehicles["hatch-20t-gdi"].spec
        prov = dict(spec.provenance)
        prov["/injectors"] = Provenance(kind=ProvenanceKind.LITERATURE, source="ficha")
        changed = spec.model_copy(update={"provenance": prov})
        fields = estimated_fields(changed)
        assert not any(p.startswith("/injectors") for p in fields)
        assert "/injectors/flow_cc_min" in estimated_fields(spec)

    def test_resolve_pointer(self, real_catalog: Catalog) -> None:
        spec: VehicleSpec = real_catalog.vehicles["hatch-20t-gdi"].spec
        assert resolve_pointer(spec, "/engine/firing_order/1") == 3
        assert resolve_pointer(spec, "") is spec
        for bad in ("engine", "/engine/x", "/gear_ratios/99", "/supercharger"):
            with pytest.raises(KeyError):
                resolve_pointer(spec, bad)

    def test_invalid_pointers(self, real_catalog: Catalog) -> None:
        spec = real_catalog.vehicles["hatch-20t-gdi"].spec
        assert invalid_provenance_pointers(spec) == []
        prov = dict(spec.provenance)
        prov["/data_version"] = Provenance(kind=ProvenanceKind.ESTIMATE)
        prov["/nada"] = Provenance(kind=ProvenanceKind.ESTIMATE)
        changed = spec.model_copy(update={"provenance": prov})
        assert invalid_provenance_pointers(changed) == ["/data_version", "/nada"]
