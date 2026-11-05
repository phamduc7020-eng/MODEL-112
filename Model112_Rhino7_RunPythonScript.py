# -*- coding: utf-8 -*-
# MODEL 112 - CHƯƠNG TRÌNH TẠO VỎ TÀU THAM SỐ | V21
# Chương trình tạo vỏ tàu chine tham số hóa cho Rhino 7 / IronPython 2.7 / RunPythonScript.
#
# CẤU TRÚC CHƯƠNG TRÌNH:
# - Chỉ có MỘT file Python duy nhất, không import các file module bên ngoài.
# - Code được chia thành các MODULE chức năng bằng tiêu đề và chú thích tiếng Việt.
# - Chế độ 1: tạo một vỏ tàu tùy chỉnh và điều chỉnh trực tiếp toàn bộ tham số.
# - Chế độ 2: tạo hệ sườn / đường nước / đường cắt dọc và thử tự động Make2D.
# - Chế độ 3: tính thủy tĩnh trực tiếp từ hình học hiện tại của Chế độ 1.
# - Chế độ 4: khảo sát tự động beta x alpha, tối đa 10 x 10 = 100 mẫu.
# - Chế độ 4 có thể tính thủy tĩnh tuần tự cho tối đa 100 mẫu tại MỘT mớn nước chung.
# - Mỗi mẫu Hydro dùng nguồn hình học tạm, tính xong giải phóng; không giữ 100 nguồn Hydro cùng lúc.
# - Chế độ 4 luôn sao chép bộ tham số MỚI NHẤT của Chế độ 1 tại thời điểm tạo mẫu.
# - Chỉ deadrise beta và bow-rake alpha được ghi đè bởi ma trận khảo sát.

import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math
import os
import io
import System
import System.Drawing
import copy
import datetime
import zipfile
import Eto.Forms as forms
import Eto.Drawing as drawing

# =============================================================================
# MODEL 112 V21-R7 - RHINO 7 / RUNPYTHONSCRIPT
# =============================================================================
MODEL112_CODE_VERSION = "V21-RC10-R7"
MODEL112_DATA_SCHEMA_VERSION = 5
MODEL112_TARGET_RHINO_MAJOR = 7
MODEL112_RUNTIME_NAME = "Rhino 7 / IronPython 2.7 / RunPythonScript"

# V19-R6 - nhánh tương thích Rhino 6; giữ nguyên kết cấu và chức năng V19:
# - Chạy bằng lệnh RunPythonScript với IronPython 2.7.
# - Không phụ thuộc module Python ngoài Rhino.
# - Bổ sung lớp tương thích cho các hàm Python có thể thiếu ở IronPython cũ.
#
# V19 - thay đổi chính:
# - Bỏ giới hạn dưới theo Z khi đo bảng tọa độ 3D: vỏ được phép nằm dưới Baseline.
# - Giá trị chiều cao bảng = Z - BaselineZ được giữ nguyên kể cả khi âm.
# - Giữ nguyên phương pháp V17: bảng tọa độ đo trực tiếp từ khung 3D.
# - Mặc định cả ba họ đường đều bắt đầu tại gốc vật lý:
#       Station 0   : X = 0
#       Waterline 0 : Z - BaselineZ = 0
#       Buttock/CD 0: Y = 0 (Centerline)
# - Station vẫn trải từ X=0 đến X=Lmax. Waterline và Buttock bắt đầu ở 0
#   nhưng không ép đường cuối đúng biên H hoặc Bmax/2 để tránh giao tuyến suy biến.
# - SOURCE_3D giữ 4 layer cố định: Station / Waterline / Buttock / HullLine.
# - DRAWING_2D vẫn gom toàn bộ hình chiếu 2D vào một layer duy nhất.

try:
    TEXT_TYPE = unicode
except NameError:
    TEXT_TYPE = str


def is_finite_number(value):
    """
    Kiểm tra số hữu hạn theo cách tương thích IronPython 2.7.
    Không dùng math.isfinite vì một số bản IronPython/Rhino cũ không có hàm này.
    """
    try:
        number = float(value)
        return (not math.isnan(number)) and (not math.isinf(number))
    except Exception:
        return False


def get_rhino_major_version():
    try:
        return int(Rhino.RhinoApp.Version.Major)
    except Exception:
        try:
            return int(str(Rhino.RhinoApp.Version).split(".")[0])
        except Exception:
            return -1


# Cấu trúc hình học chính:
# - Dải đáy, sống tàu và vùng forefoot được quản lý theo các mặt riêng.
# - Upper outer chine và vách đuôi nghiêng dùng cấu hình hình học hiện tại.

# =============================================================================
# MODULE 0: QUẢN LÝ ĐƠN VỊ RHINO
# =============================================================================
                                                           
#
# Quy ước:
# - Giao diện Model 112 vẫn nhập kích thước theo MÉT.
# - Geometry nội bộ luôn được đổi sang MODEL UNIT hiện tại của Rhino.
# - Chế độ 3 luôn trả kết quả theo m, m², m³.
#
# Ví dụ:
#   Document = Millimeters  -> 1 m = 1000 model units
#   Document = Centimeters  -> 1 m = 100 model units
#   Document = Meters       -> 1 m = 1 model unit
#   Document = Inches       -> 1 m ≈ 39.3700787 model units
# =============================================================================


def get_document_units_per_meter():
    """
    Số model unit tương ứng với 1 mét trong document Rhino hiện tại.
    """
    try:
        value = Rhino.RhinoMath.UnitScale(
            Rhino.UnitSystem.Meters,
            sc.doc.ModelUnitSystem
        )

        value = float(value)

        if value > 0.0 and is_finite_number(value):
            return value
    except Exception:
        pass

    # Fallback an toàn cho Rhino/IronPython nếu UnitScale không trả được.
    unit_system = sc.doc.ModelUnitSystem

    fallback_map = {
        Rhino.UnitSystem.Millimeters: 1000.0,
        Rhino.UnitSystem.Centimeters: 100.0,
        Rhino.UnitSystem.Decimeters: 10.0,
        Rhino.UnitSystem.Meters: 1.0,
        Rhino.UnitSystem.Kilometers: 0.001,
        Rhino.UnitSystem.Inches: 39.37007874015748,
        Rhino.UnitSystem.Feet: 3.280839895013123
    }

    if unit_system in fallback_map:
        return float(
            fallback_map[unit_system]
        )

    raise Exception(
        u"Model 112 không xác định được hệ đơn vị của document Rhino. "
        u"Hãy dùng Millimeters, Centimeters, Meters, Inches hoặc Feet."
    )


def model_units_from_meters(value_m, units_per_meter=None):
    """Đổi mét sang model units hiện tại."""
    if units_per_meter is None:
        units_per_meter = get_document_units_per_meter()

    return (
        float(value_m) *
        float(units_per_meter)
    )


def model_units_from_mm(value_mm, units_per_meter=None):
    """Đổi millimeter kỹ thuật sang model units hiện tại."""
    return model_units_from_meters(
        float(value_mm) / 1000.0,
        units_per_meter
    )


def model_units_to_meters(value_model, units_per_meter=None):
    """Đổi model units hiện tại sang mét."""
    if units_per_meter is None:
        units_per_meter = get_document_units_per_meter()

    units_per_meter = float(
        units_per_meter
    )

    if units_per_meter <= 0.0:
        return 0.0

    return (
        float(value_model) /
        units_per_meter
    )


def model_units_to_mm(value_model, units_per_meter=None):
    """Đổi model units hiện tại sang millimeter."""
    return (
        model_units_to_meters(
            value_model,
            units_per_meter
        ) *
        1000.0
    )


def model_area_to_m2(value_area, units_per_meter=None):
    if units_per_meter is None:
        units_per_meter = get_document_units_per_meter()

    scale = float(
        units_per_meter
    )

    return (
        float(value_area) /
        (scale * scale)
    )


def model_volume_to_m3(value_volume, units_per_meter=None):
    if units_per_meter is None:
        units_per_meter = get_document_units_per_meter()

    scale = float(
        units_per_meter
    )

    return (
        float(value_volume) /
        (scale * scale * scale)
    )


def document_unit_name():
    try:
        return str(
            sc.doc.ModelUnitSystem
        )
    except Exception:
        return "Unknown"




def ensure_document_units_match_parameters(
    params,
    operation_name=u"thực hiện thao tác"
):
    """
    Ngăn lỗi scale khi người dùng đổi ModelUnitSystem sau khi mở MODEL 112.

    Tham số trong form đã được quy đổi sang model unit tại thời điểm mở form.
    Nếu Document Units đổi giữa chừng thì tiếp tục dùng bộ số cũ có thể làm
    hình học sai 1000 lần. V19 dừng sớm và yêu cầu mở lại giao diện.
    """
    current_units_per_meter = float(
        get_document_units_per_meter()
    )

    stored_units_per_meter = float(
        getattr(
            params,
            "units_per_meter",
            current_units_per_meter
        )
    )

    scale_tolerance = max(
        1.0e-12,
        abs(stored_units_per_meter) * 1.0e-12
    )

    if abs(
        current_units_per_meter -
        stored_units_per_meter
    ) > scale_tolerance:
        raise Exception(
            (
                u"Đơn vị Document đã thay đổi sau khi mở MODEL 112. "
                u"Không tiếp tục %s để tránh sai tỷ lệ hình học. "
                u"Hãy đóng giao diện, kiểm tra Units của Rhino rồi mở MODEL 112 lại. "
                u"Document hiện tại: %s."
            ) % (
                operation_name,
                document_unit_name()
            )
        )

    return current_units_per_meter

# MODULE 1: THAM SỐ ĐẦU VÀO CỦA MODEL 112
# Nhiệm vụ: lưu toàn bộ dữ liệu người dùng có thể thay đổi và các thiết lập nền.
# HullParameters là nguồn dữ liệu chính dùng chung cho toàn chương trình.

class HullParameters(object):
    def __init__(self):
        self.model_version = (
            "Model 112 - Chương trình tạo vỏ tàu tham số"
        )

        # 1A. Kích thước chính của tàu
                                                   
        self.units_per_meter = (
            get_document_units_per_meter()
        )

        self.document_unit_system = (
            document_unit_name()
        )

        self.length = model_units_from_meters(
            24.0,
            self.units_per_meter
        )

        self.beam = model_units_from_meters(
            6.5,
            self.units_per_meter
        )

        self.depth = model_units_from_meters(
            5.0,
            self.units_per_meter
        )

        self.draft = model_units_from_meters(
            2.5,
            self.units_per_meter
        )

        self.baseline_z = 0.0

        # 1B. Hai tham số nghiên cứu chính: deadrise beta và bow-rake alpha
        # Giá trị ban đầu dùng để tạo một vỏ tàu đơn ở Chế độ 1.
        self.deadrise_midship_angle = 7.0
        self.bow_rake_angle = 35.0

        # Khi bật liên kết deadrise, góc deadrise đuôi và mũi sẽ chạy theo beta giữa tàu.
        self.link_deadrise_profile = False
        self.deadrise_stern_angle = 7.0
        self.deadrise_bow_angle = 7.0
        self.deadrise_midship_x_ratio = 0.50

        # Số đường gãy hình học trên mỗi mạn. Cho phép 1-3 đường.
        # 1: lower chine; 2: thêm upper inner; 3: thêm upper outer.
        self.total_knuckle_count_per_side = 3

        # 1C. Các tham số hình dáng nâng cao
        self.lower_chine_bow_end_height = (
            1.10 * self.units_per_meter
        )

        # Chiều rộng toàn phần của dải keel phẳng.
        # Giá trị mặc định tương đương tỷ lệ cũ 0.052 * Bmax.
        # Bk = 0 nghĩa là không có dải keel phẳng riêng.
        self.keel_width = (
            self.beam *
            0.052
        )

        # Biến legacy giữ để tương thích với các phần code/csv cũ.
        self.keel_width_ratio = (
            self.keel_width /
            self.beam
            if self.beam > 0.0
            else 0.0
        )

        self.stern_height_ratio = 0.25
        self.body_base_height_ratio = 0.00
        self.c_height_ratio = 0.04

        self.stem_tip_height_ratio = 1.00
        self.stem_p1_along_ratio = 0.08
        self.stem_p1_height_ratio = 0.12
        self.stem_p2_along_ratio = 0.38
        self.stem_p2_height_ratio = 0.46
        self.stem_p3_along_ratio = 0.72
        self.stem_p3_height_ratio = 0.80

        self.lower_chine_max_beam_ratio = 0.72
        self.lower_chine_stern_beam_factor = 0.90
        self.lower_chine_flare1_x_ratio = 0.08
        self.lower_chine_flare1_beam_factor = 0.96
        self.lower_chine_flare2_x_ratio = 0.22
        self.lower_chine_flare2_beam_factor = 0.99
        self.lower_chine_full1_x_ratio = 0.45
        self.lower_chine_full2_x_ratio = 0.64
        self.bow_body_start_ratio = 0.72
        self.lower_chine_bow_start_beam_factor = 0.97

        self.upper_chine_inner_height_ratio = 0.60
        self.upper_chine_inner_max_beam_ratio = 0.88

                                                                         
        # Giá trị 0.35 làm upper chine rời vách đuôi êm hơn, giảm độ võng lớn
        # trong 1/3 chiều dài phía sau và gần đường nét của mẫu tham chiếu hơn.
        self.upper_chine_keel_follow_factor = 0.35
        self.upper_chine_stem_join_height_ratio = 0.72
        self.upper_chine_outer_height_gap = (
            0.10 * self.units_per_meter
        )
        self.upper_chine_outer_side_gap = (
            0.10 * self.units_per_meter
        )
        self.upper_chine_gap_taper_start = 0.75

        self.sheer_max_beam_ratio = 0.985
        self.sheer_stern_beam_factor = 0.965
        self.sheer_flare1_beam_factor = 0.99
        self.sheer_flare2_beam_factor = 1.00
        self.sheer_bow_start_beam_factor = 0.99
        self.sheer_bow_shoulder_x_ratio = 0.60
        self.sheer_bow_shoulder_beam_factor = 1.01
        self.sheer_stern_height_ratio = 0.90
        self.sheer_bow_start_height_ratio = 0.92
        self.sheer_sag_depth_ratio = 0.050
        self.sheer_sag_position_ratio = 0.52
        self.sheer_sag_shape_power = 1.00
        self.sheer_stem_join_height_ratio = 1.00

        self.sheer_bow_entry_handle_ratio = 0.10
        self.sheer_bow_stem_handle_ratio = 0.055
        self.sheer_bow_stem_control_outboard_fraction = 0.60
        self.sheer_bow_stem_control_height_fraction = 0.20

                
        # Không tách bottom thành body + forefoot.
        # Nếu tách, bottom được tạo bởi create_split_bottom_panels() (Loft cũ)
        # và không còn dùng chung Lower Chine rail với lower-side.
        self.split_bottom_at_keel_stem = False
        self.split_side_panels_at_bow = True

                                                               
        #
        # False:
        #   Chế độ 1 vẫn dựng mặt theo topology/loft hiện tại để giữ nguyên
        #   hình dáng mà người dùng đã hiệu chỉnh.
        #
        # True:
        #   Các dải mặt dùng đường dọc keel/chine/sheer làm hai rail thật
        #   của Sweep2. Chế độ 3 tự bật giá trị này trên bản sao tạm.
        self.use_longitudinal_rail_surfaces = False

        self.bottom_topology_mode = (
            "_KEEL_BODY_STEM_SPLIT"
        )
        self.bow_entry_vertical_tangent_scale = 0.55
        self.sheer_bow_entry_vertical_tangent_scale = 0.72

        self.create_raked_broken_transom = True
        self.transom_rake_angle = 12.0
                                                                           
        # cắt keel; vị trí cắt được tính tự động từ góc nghiêng vách đuôi.
        self.transom_keel_forward_offset = (
            0.47 * self.units_per_meter
        )
        self.transom_lower_chine_break_offset = (
            0.00 * self.units_per_meter
        )
        self.transom_upper_inner_break_offset = (
            0.00 * self.units_per_meter
        )
        self.transom_upper_outer_break_offset = (
            0.00 * self.units_per_meter
        )
        self.transom_sheer_break_offset = 0.00

        # -----------------------------------------------------------------
                                  
        # -----------------------------------------------------------------
        # - Vách đuôi mặc định nghiêng 12 độ để gần mẫu tham chiếu hơn.
        # - Các break offset của vách đuôi đặt về 0 để đường bao đuôi thẳng, sạch.
        # - Chine dưới ở vùng đuôi hẹp hơn một chút để tăng độ loe mặt cắt đuôi.
        # - Chine trên chỉ theo 35% độ nâng keel ở đuôi để giảm độ cong dọc.
        # - Sheer dùng đường chuyển tiếp C2 (smootherstep), giảm võng mặc định và
        #   kéo điểm thấp nhất về phía trước để đoạn rời vách đuôi dài, êm hơn.

        # 1D. Tham số phương pháp tạo đường cong và bề mặt
        self.body_station_count = 7
        self.bow_fairing_section_count = 2
        self.maximum_total_section_count = 21
        self.use_cosine_body_station_distribution = True

        self.bow_entry_handle_ratio = 0.080
        self.bow_stem_handle_ratio = 0.060
        self.bow_stem_control_outboard_fraction = 0.52
        self.bow_stem_control_height_fraction = 0.20

        self.lower_side_body_bulge_ratio = 0.018
        self.lower_side_bow_bulge_ratio = 0.018
        self.upper_side_body_bulge_ratio = 0.010
        self.upper_side_bow_bulge_ratio = 0.012

        self.curve_degree = 3
        self.loft_type = rg.LoftType.Normal
        self.join_tolerance_factor = 2.0
        self.loft_refit_tolerance = 0.0

        # 1E. Tham số hiển thị và xuất dữ liệu
        # Giữ show_longitudinal_curves để tương thích các phần code cũ,
        # nhưng giao diện mới cho phép điều khiển riêng Keel / Chine / Sheer.
        self.show_keel_curve = True
        self.show_chine_curves = True
        self.show_sheer_curve = True
        self.show_longitudinal_curves = True

        self.show_body_stations = False
        self.show_bow_fairing_sections = False
        self.show_design_points = False

        # Khung vách đuôi là hệ curve riêng, không phải surface transom.
        self.show_transom_frame = True

        # False = tạo đủ hai mạn.
        # True  = chỉ tạo mạn phải / Starboard cho Chế độ 1, 2 và 4.
        # Chế độ 3 thủy tĩnh luôn ép về full hull để không làm sai V/Delta.
        self.create_half_model = False

        self.create_hull_surfaces = True
        self.create_transom_surfaces = True
        self.create_deck_surface = False

        # -----------------------------------------------------------------
                                          
        # -----------------------------------------------------------------
        # Mặc định KHÔNG Join các mặt thành một polysurface.
        # Mỗi panel vỏ được đưa vào Rhino dưới dạng một Brep/Surface riêng,
        # nên người dùng có thể:
        # - click chọn riêng một mặt;
        # - Delete riêng một mặt;
        # - ShowEdges / JoinEdge thủ công;
        # - chọn một nửa tàu để tính/đối chiếu;
        # - kiểm tra từng panel mà không chọn cả tàu.
        self.join_hull_surfaces = False
        self.add_individual_surfaces_when_join_fails = True

        # Khi tạo tàu cuối, chỉ các Curve/Point của layer "khung" được group.
        # Surface trên layer "mặt tàu" tuyệt đối không đưa vào group.
        self.group_framework_only = True

        # -----------------------------------------------------------------
                                            
        # -----------------------------------------------------------------
        # Hai mặt:
        #   bottom <-> lower_side
        # phải dùng CHÍNH XÁC cùng một lower-chine rail.
        #
        # Đồng thời:
        # - bottom KHÔNG tách body/forefoot;
        # - lower_side KHÔNG tách body/bow.
        #
        # Nhờ đó một edge Lower Chine dài của Bottom ghép 1-1 với đúng một
        # edge Lower Chine dài của Lower Side, thay vì 1 edge phải ghép với
        # nhiều edge rời. hai naked edge màu hồng.
        self.force_shared_lower_chine_edge = True

        self.create_design_waterline = False

        self.export_parameter_table = True
        self.export_station_table = True
        self.data_output_folder_name = "Model112_Data"

        # 1F. Giá trị khởi tạo cho giao diện khảo sát.
        # Đây CHỈ là giá trị điền sẵn ban đầu; người dùng có thể sửa trực tiếp và không bị giới hạn 25 mẫu.
        self.survey_default_deadrise_values = [
            0.0,
            4.0,
            7.0,
            12.0,
            15.0
        ]
        self.survey_default_bow_rake_values = [
            27.0,
            31.0,
            35.0,
            39.0,
            43.0
        ]

        # Giới hạn nhập tương tác của beta, alpha và số chine.
        self.deadrise_slider_min = 0.0
        self.deadrise_slider_max = 30.0
        self.deadrise_slider_step = 1.0

        self.bow_rake_slider_min = 27.0
        self.bow_rake_slider_max = 43.0
        self.bow_rake_slider_step = 1.0

        self.knuckle_count_min = 1
        self.knuckle_count_max = 3

        self.survey_spacing_x_factor = 1.18
        self.survey_spacing_y_factor = 1.80


# MODULE 2: TÍNH TOÁN CÁC THAM SỐ PHỤ THUỘC
# Nhiệm vụ: tính các đại lượng không nhập trực tiếp như half-beam, keel width,
# vị trí sống mũi, đường nước thiết kế... từ bộ tham số của Module 1.

class DerivedHullData(object):
    def __init__(self, params):
        self.half_beam = params.beam * 0.5
        self.keel_width = max(
            0.0,
            float(
                getattr(
                    params,
                    "keel_width",
                    params.beam *
                    getattr(
                        params,
                        "keel_width_ratio",
                        0.0
                    )
                )
            )
        )
        self.half_keel_width = (
            self.keel_width *
            0.5
        )
        self.waterline_z = (
            params.baseline_z +
            params.draft
        )

        self.stem_start_z = (
            params.depth *
            params.c_height_ratio
        )
        self.stem_tip_z = (
            params.depth *
            params.stem_tip_height_ratio
        )
        self.stem_vertical_rise = (
            self.stem_tip_z -
            self.stem_start_z
        )
        self.stem_horizontal_run = (
            self.stem_vertical_rise *
            math.tan(
                math.radians(
                    params.bow_rake_angle
                )
            )
        )
        self.stem_start_x = (
            params.length -
            self.stem_horizontal_run
        )
        self.stem_start_ratio = (
            self.stem_start_x /
            params.length
        )


class StationRecord(object):
    def __init__(
        self,
        station_id,
        section_kind,
        keel_point,
        lower_point,
        upper_inner_point,
        upper_outer_point,
        sheer_point,
        length
    ):
        self.station_id = station_id
        self.section_kind = section_kind
        self.keel_point = keel_point
        self.lower_point = lower_point
        self.upper_inner_point = upper_inner_point
        self.upper_outer_point = upper_outer_point
        self.sheer_point = sheer_point

        reference_point = (
            lower_point or
            upper_inner_point or
            upper_outer_point or
            sheer_point or
            keel_point
        )

        if reference_point is None:
            raise Exception(
                "StationRecord requires at least one geometric point."
            )

        self.reference_x = reference_point.X
        self.reference_x_ratio = (
            self.reference_x /
            length
        )


PARAMS = HullParameters()
DERIVED = DerivedHullData(PARAMS)


# MODULE 3: LIÊN KẾT THAM SỐ VỚI LÕI HÌNH HỌC
# Các hàm hình học cũ sử dụng tên biến toàn cục.
# Module này nhận dữ liệu từ HullParameters rồi đồng bộ các biến để toàn bộ lõi hình học dùng cùng một nguồn dữ liệu.

ModelVersion = PARAMS.model_version
GeometryUnitsPerMeter = PARAMS.units_per_meter

L = PARAMS.length
B = PARAMS.beam
H = PARAMS.depth
T = PARAMS.draft
BaselineZ = PARAMS.baseline_z

KeelWidth = DERIVED.keel_width
KeelWidthRatio = (
    KeelWidth /
    B
    if B > 0.0
    else 0.0
)
SternHeightRatio = PARAMS.stern_height_ratio
BodyBaseHeightRatio = PARAMS.body_base_height_ratio
CHeightRatio = PARAMS.c_height_ratio

BowRakeAngle = PARAMS.bow_rake_angle
StemTipHeightRatio = PARAMS.stem_tip_height_ratio
StemP1AlongRatio = PARAMS.stem_p1_along_ratio
StemP1HeightRatio = PARAMS.stem_p1_height_ratio
StemP2AlongRatio = PARAMS.stem_p2_along_ratio
StemP2HeightRatio = PARAMS.stem_p2_height_ratio
StemP3AlongRatio = PARAMS.stem_p3_along_ratio
StemP3HeightRatio = PARAMS.stem_p3_height_ratio

DeadriseSternAngle = PARAMS.deadrise_stern_angle
DeadriseMidshipAngle = PARAMS.deadrise_midship_angle
DeadriseBowAngle = PARAMS.deadrise_bow_angle
DeadriseMidshipXRatio = PARAMS.deadrise_midship_x_ratio
LowerChineBowEndHeight = (
    PARAMS.lower_chine_bow_end_height
)

LowerChineMaxBeamRatio = (
    PARAMS.lower_chine_max_beam_ratio
)
LowerChineSternBeamFactor = (
    PARAMS.lower_chine_stern_beam_factor
)
LowerChineFlare1XRatio = (
    PARAMS.lower_chine_flare1_x_ratio
)
LowerChineFlare1BeamFactor = (
    PARAMS.lower_chine_flare1_beam_factor
)
LowerChineFlare2XRatio = (
    PARAMS.lower_chine_flare2_x_ratio
)
LowerChineFlare2BeamFactor = (
    PARAMS.lower_chine_flare2_beam_factor
)
LowerChineFull1XRatio = (
    PARAMS.lower_chine_full1_x_ratio
)
LowerChineFull2XRatio = (
    PARAMS.lower_chine_full2_x_ratio
)
BowBodyStartRatio = PARAMS.bow_body_start_ratio
LowerChineBowStartBeamFactor = (
    PARAMS.lower_chine_bow_start_beam_factor
)

UpperChineInnerHeightRatio = (
    PARAMS.upper_chine_inner_height_ratio
)
UpperChineInnerMaxBeamRatio = (
    PARAMS.upper_chine_inner_max_beam_ratio
)
UpperChineKeelFollowFactor = (
    PARAMS.upper_chine_keel_follow_factor
)
UpperChineStemJoinHeightRatio = (
    PARAMS.upper_chine_stem_join_height_ratio
)
UpperChineOuterHeightGap = (
    PARAMS.upper_chine_outer_height_gap
)
UpperChineOuterSideGap = (
    PARAMS.upper_chine_outer_side_gap
)
UpperChineGapTaperStart = (
    PARAMS.upper_chine_gap_taper_start
)

TotalKnuckleCountPerSide = (
    PARAMS.total_knuckle_count_per_side
)

SheerMaxBeamRatio = PARAMS.sheer_max_beam_ratio
SheerSternBeamFactor = PARAMS.sheer_stern_beam_factor
SheerFlare1BeamFactor = PARAMS.sheer_flare1_beam_factor
SheerFlare2BeamFactor = PARAMS.sheer_flare2_beam_factor
SheerBowStartBeamFactor = (
    PARAMS.sheer_bow_start_beam_factor
)
SheerBowShoulderXRatio = (
    PARAMS.sheer_bow_shoulder_x_ratio
)
SheerBowShoulderBeamFactor = (
    PARAMS.sheer_bow_shoulder_beam_factor
)
SheerSternHeightRatio = PARAMS.sheer_stern_height_ratio
SheerBowStartHeightRatio = (
    PARAMS.sheer_bow_start_height_ratio
)
SheerSagDepthRatio = PARAMS.sheer_sag_depth_ratio
SheerSagPositionRatio = PARAMS.sheer_sag_position_ratio
SheerSagShapePower = PARAMS.sheer_sag_shape_power
SheerStemJoinHeightRatio = (
    PARAMS.sheer_stem_join_height_ratio
)

SheerBowEntryHandleRatio = (
    PARAMS.sheer_bow_entry_handle_ratio
)
SheerBowStemHandleRatio = (
    PARAMS.sheer_bow_stem_handle_ratio
)
SheerBowStemControlOutboardFraction = (
    PARAMS.sheer_bow_stem_control_outboard_fraction
)
SheerBowStemControlHeightFraction = (
    PARAMS.sheer_bow_stem_control_height_fraction
)

SplitBottomAtKeelStem = (
    PARAMS.split_bottom_at_keel_stem
)
SplitSidePanelsAtBow = PARAMS.split_side_panels_at_bow

                                                     
UseLongitudinalRailSurfaces = (
    PARAMS.use_longitudinal_rail_surfaces
)

BottomTopologyMode = PARAMS.bottom_topology_mode
BowEntryVerticalTangentScale = (
    PARAMS.bow_entry_vertical_tangent_scale
)
SheerBowEntryVerticalTangentScale = (
    PARAMS.sheer_bow_entry_vertical_tangent_scale
)

CreateRakedBrokenTransom = (
    PARAMS.create_raked_broken_transom
)
TransomRakeAngle = PARAMS.transom_rake_angle
TransomKeelForwardOffset = (
    PARAMS.transom_keel_forward_offset
)
TransomLowerChineBreakOffset = (
    PARAMS.transom_lower_chine_break_offset
)
TransomUpperInnerBreakOffset = (
    PARAMS.transom_upper_inner_break_offset
)
TransomUpperOuterBreakOffset = (
    PARAMS.transom_upper_outer_break_offset
)
TransomSheerBreakOffset = (
    PARAMS.transom_sheer_break_offset
)

BodyStationCount = PARAMS.body_station_count
BowFairingSectionCount = (
    PARAMS.bow_fairing_section_count
)
MaximumTotalSectionCount = (
    PARAMS.maximum_total_section_count
)
UseCosineBodyStationDistribution = (
    PARAMS.use_cosine_body_station_distribution
)

BowEntryHandleRatio = PARAMS.bow_entry_handle_ratio
BowStemHandleRatio = PARAMS.bow_stem_handle_ratio
BowStemControlOutboardFraction = (
    PARAMS.bow_stem_control_outboard_fraction
)
BowStemControlHeightFraction = (
    PARAMS.bow_stem_control_height_fraction
)

LowerSideBodyBulgeRatio = (
    PARAMS.lower_side_body_bulge_ratio
)
LowerSideBowBulgeRatio = (
    PARAMS.lower_side_bow_bulge_ratio
)
UpperSideBodyBulgeRatio = (
    PARAMS.upper_side_body_bulge_ratio
)
UpperSideBowBulgeRatio = (
    PARAMS.upper_side_bow_bulge_ratio
)

CurveDegree = PARAMS.curve_degree
LoftType = PARAMS.loft_type
JoinToleranceFactor = PARAMS.join_tolerance_factor
LoftRefitTolerance = PARAMS.loft_refit_tolerance

ShowKeelCurve = bool(
    getattr(
        PARAMS,
        "show_keel_curve",
        PARAMS.show_longitudinal_curves
    )
)
ShowChineCurves = bool(
    getattr(
        PARAMS,
        "show_chine_curves",
        PARAMS.show_longitudinal_curves
    )
)
ShowSheerCurve = bool(
    getattr(
        PARAMS,
        "show_sheer_curve",
        PARAMS.show_longitudinal_curves
    )
)
ShowLongitudinalCurves = bool(
    ShowKeelCurve or
    ShowChineCurves or
    ShowSheerCurve
)
ShowBodyStations = PARAMS.show_body_stations
ShowBowFairingSections = PARAMS.show_bow_fairing_sections
ShowDesignPoints = PARAMS.show_design_points
ShowTransomFrame = bool(
    getattr(
        PARAMS,
        "show_transom_frame",
        True
    )
)
CreateHalfModel = bool(
    getattr(
        PARAMS,
        "create_half_model",
        False
    )
)

CreateHullSurfaces = PARAMS.create_hull_surfaces
CreateTransomSurfaces = PARAMS.create_transom_surfaces
CreateDeckSurface = PARAMS.create_deck_surface
JoinHullSurfaces = PARAMS.join_hull_surfaces
AddIndividualSurfacesWhenJoinFails = (
    PARAMS.add_individual_surfaces_when_join_fails
)

        
# True = chỉ group Curve/Point; Brep/Surface luôn độc lập.
GroupFrameworkOnly = PARAMS.group_framework_only

        
# Bottom và lower-side dùng chung một lower-chine rail thật.
ForceSharedLowerChineEdge = (
    PARAMS.force_shared_lower_chine_edge
)
CreateDesignWaterline = PARAMS.create_design_waterline

ExportParameterTable = PARAMS.export_parameter_table
ExportStationTable = PARAMS.export_station_table
DataOutputFolderName = PARAMS.data_output_folder_name


def build_parameter_catalog(params):
    return [
        (
            "A_MAIN_DIMENSIONS",
            "Lmax",
            "length",
            "m",
            model_units_to_meters(
                params.length,
                params.units_per_meter
            ),
            "Maximum hull length Lmax"
        ),
        (
            "A_MAIN_DIMENSIONS",
            "Bmax",
            "beam",
            "m",
            model_units_to_meters(
                params.beam,
                params.units_per_meter
            ),
            "Maximum hull beam Bmax"
        ),
        (
            "A_MAIN_DIMENSIONS",
            "H",
            "depth",
            "m",
            model_units_to_meters(
                params.depth,
                params.units_per_meter
            ),
            "Maximum hull height H"
        ),
        (
            "A_MAIN_DIMENSIONS",
            "T",
            "draft",
            "m",
            model_units_to_meters(
                params.draft,
                params.units_per_meter
            ),
            "Design draft"
        ),
        (
            "A_MAIN_DIMENSIONS",
            "Bk",
            "keel_width",
            "m",
            model_units_to_meters(
                getattr(
                    params,
                    "keel_width",
                    0.0
                ),
                params.units_per_meter
            ),
            "Full flat-keel width; zero means no flat keel strip"
        ),
        (
            "B_PRIMARY_RESEARCH",
            "beta",
            "deadrise_midship_angle",
            "deg",
            params.deadrise_midship_angle,
            "Research bottom deadrise angle beta"
        ),
        (
            "B_PRIMARY_RESEARCH",
            "alpha",
            "bow_rake_angle",
            "deg",
            params.bow_rake_angle,
            "Research bow-rake angle"
        ),
        (
            "B_PRIMARY_RESEARCH",
            "N_chine",
            "total_knuckle_count_per_side",
            "count",
            params.total_knuckle_count_per_side,
            "Geometric knuckle-line count per side"
        ),
        (
            "C_ADVANCED_SHAPE",
            "beta_T",
            "deadrise_stern_angle",
            "deg",
            params.deadrise_stern_angle,
            "Stern deadrise in independent-profile mode"
        ),
        (
            "C_ADVANCED_SHAPE",
            "beta_B",
            "deadrise_bow_angle",
            "deg",
            params.deadrise_bow_angle,
            "Bow deadrise in independent-profile mode"
        ),
        (
            "C_ADVANCED_SHAPE",
            "Z_B",
            "lower_chine_bow_end_height",
            "m",
            model_units_to_meters(
                params.lower_chine_bow_end_height,
                params.units_per_meter
            ),
            "Lower chine end height on stem"
        ),
        (
            "C_ADVANCED_SHAPE",
            "Y_LC",
            "lower_chine_max_beam_ratio",
            "ratio",
            params.lower_chine_max_beam_ratio,
            "Maximum lower chine half-beam ratio"
        ),
        (
            "C_ADVANCED_SHAPE",
            "Z_UI",
            "upper_chine_inner_height_ratio",
            "ratio",
            params.upper_chine_inner_height_ratio,
            "Upper inner chine height ratio"
        ),
        (
            "C_ADVANCED_SHAPE",
            "dZ_UO",
            "upper_chine_outer_height_gap",
            "m",
            model_units_to_meters(
                params.upper_chine_outer_height_gap,
                params.units_per_meter
            ),
            "Outer upper chine vertical offset"
        ),
        (
            "C_ADVANCED_SHAPE",
            "dY_UO",
            "upper_chine_outer_side_gap",
            "m",
            model_units_to_meters(
                params.upper_chine_outer_side_gap,
                params.units_per_meter
            ),
            "Outer upper chine outboard offset"
        ),
        (
            "C_ADVANCED_SHAPE",
            "S_sheer",
            "sheer_sag_depth_ratio",
            "ratio",
            params.sheer_sag_depth_ratio,
            "Sheer sag depth ratio"
        ),
        (
            "C_ADVANCED_SHAPE",
            "beta_TR",
            "transom_rake_angle",
            "deg",
            params.transom_rake_angle,
            "Transom rake angle"
        ),
        (
            "D_METHOD",
            "N_body",
            "body_station_count",
            "count",
            params.body_station_count,
            "Number of body stations"
        ),
        (
            "D_METHOD",
            "N_bow",
            "bow_fairing_section_count",
            "count",
            params.bow_fairing_section_count,
            "Number of bow fairing sections"
        ),
        (
            "D_METHOD",
            "p",
            "curve_degree",
            "degree",
            params.curve_degree,
            "NURBS curve degree"
        ),
        (
            "D_METHOD",
            "topology",
            "bottom_topology_mode",
            "text",
            params.bottom_topology_mode,
            "Bottom surface topology"
        ),
        (
            "F_SURVEY_GRID",
            "beta_grid",
            "survey_default_deadrise_values",
            "deg",
            ";".join(
                [str(value) for value in params.survey_default_deadrise_values]
            ),
            "Gia tri beta khoi tao cho giao dien khao sat"
        ),
        (
            "F_SURVEY_GRID",
            "alpha_grid",
            "survey_default_bow_rake_values",
            "deg",
            ";".join(
                [str(value) for value in params.survey_default_bow_rake_values]
            ),
            "Gia tri alpha khoi tao cho giao dien khao sat"
        )
    ]


PARAMETER_CATALOG = build_parameter_catalog(PARAMS)



class ParameterSpec(object):
    def __init__(
        self,
        key,
        label,
        minimum,
        maximum,
        step,
        unit,
        group,
        decimals,
        display_scale,
        tooltip
    ):
        self.key = key
        self.label = label
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.unit = unit
        self.group = group
        self.decimals = decimals
        self.display_scale = display_scale
        self.tooltip = tooltip


def build_ui_parameter_specs(params):
    # Toàn bộ nhãn hiển thị được Việt hóa. Tên biến nội bộ vẫn giữ tiếng Anh
    # để không ảnh hưởng thuật toán và thuận tiện khi đối chiếu tài liệu kỹ thuật.
    return [
        ParameterSpec(
            "deadrise_midship_angle",
            u"Góc vát đáy β",
            params.deadrise_slider_min,
            params.deadrise_slider_max,
            params.deadrise_slider_step,
            u"độ",
            "Research",
            0,
            1.0,
            u"Góc vát đáy β tại vùng thân giữa, dùng cho thiết kế và khảo sát. Khoảng điều chỉnh 0-30 độ."
        ),
        ParameterSpec(
            "bow_rake_angle",
            u"Góc nghiêng sống mũi α",
            params.bow_rake_slider_min,
            params.bow_rake_slider_max,
            params.bow_rake_slider_step,
            u"độ",
            "Research",
            0,
            1.0,
            u"Góc nghiêng sống mũi α. Khoảng khảo sát thiết lập 27-43 độ."
        ),
        ParameterSpec(
            "total_knuckle_count_per_side",
            u"Số đường gãy góc mỗi mạn",
            float(params.knuckle_count_min),
            float(params.knuckle_count_max),
            1.0,
            u"đường",
            "Research",
            0,
            1.0,
            u"Số đường gãy hình học trên mỗi mạn. Cho phép từ 1 đến 3 đường; 1 là Lower Chine, 2 thêm Upper Inner, 3 thêm Upper Outer."
        ),
        ParameterSpec(
            "length",
            u"Chiều dài tàu Lmax",
            18.0,
            30.0,
            0.1,
            u"m",
            "Dimensions",
            1,
            params.units_per_meter,
            u"Chiều dài lớn nhất Lmax dùng để tạo hình vỏ tàu."
        ),
        ParameterSpec(
            "beam",
            u"Chiều rộng tàu Bmax",
            4.5,
            8.0,
            0.05,
            u"m",
            "Dimensions",
            2,
            params.units_per_meter,
            u"Chiều rộng lớn nhất Bmax của vỏ tàu."
        ),
        ParameterSpec(
            "depth",
            u"Chiều cao lớn nhất H",
            2.0,
            7.0,
            0.05,
            u"m",
            "Dimensions",
            2,
            params.units_per_meter,
            u"Chiều cao lớn nhất H tính từ đường cơ bản đến cao độ lớn nhất của thân tàu; phạm vi 2-7 m."
        ),
        ParameterSpec(
            "draft",
            u"Chiều chìm T",
            1.0,
            4.5,
            0.05,
            u"m",
            "Dimensions",
            2,
            params.units_per_meter,
            u"Chiều chìm thiết kế T; giá trị phải nhỏ hơn chiều cao mạn H."
        ),
        ParameterSpec(
            "keel_width",
            u"Chiều rộng keel Bk",
            0.0,
            1.50,
            0.01,
            u"m",
            "Dimensions",
            3,
            params.units_per_meter,
            u"Chiều rộng toàn phần của dải keel phẳng. Bk = 0 nghĩa là không có dải keel phẳng; hai panel đáy gặp nhau tại mặt phẳng dọc tâm."
        ),
        ParameterSpec(
            "stern_height_ratio",
            u"Tỷ lệ cao độ sống đáy tại đuôi kKT",
            0.00,
            0.50,
            0.01,
            u"H",
            "Dimensions",
            2,
            1.0,
            u"Cao độ sống đáy tại đuôi theo tỷ lệ H: ZKT = kKT·H. Cho phép 0 để tạo đáy đuôi thấp/phẳng hơn."
        ),
        ParameterSpec(
            "lower_chine_bow_end_height",
            u"Cao độ đầu đường gãy dưới tại mũi ZB",
            0.30,
            2.50,
            0.05,
            u"m",
            "Chine and Sheer",
            2,
            params.units_per_meter,
            u"Cao độ thực nơi đường gãy dưới kết thúc tại sống mũi."
        ),
        ParameterSpec(
            "lower_chine_max_beam_ratio",
            u"Tỷ lệ nửa rộng đường gãy dưới",
            0.55,
            0.85,
            0.01,
            u"tỷ lệ",
            "Chine and Sheer",
            2,
            1.0,
            u"Tỷ lệ nửa rộng lớn nhất của đường gãy dưới so với nửa chiều rộng tàu."
        ),
        ParameterSpec(
            "lower_chine_stern_beam_factor",
            u"Độ đầy đường gãy dưới tại đuôi",
            0.70,
            1.00,
            0.01,
            u"tỷ lệ",
            "Chine and Sheer",
            2,
            1.0,
            u"Điều chỉnh độ rộng của đường gãy dưới tại vách đuôi. Giảm giá trị sẽ làm đáy đuôi gọn và mặt cắt loe rõ hơn."
        ),
        ParameterSpec(
            "upper_chine_inner_height_ratio",
            u"Tỷ lệ cao đường gãy trên",
            0.45,
            0.72,
            0.01,
            u"tỷ lệ",
            "Chine and Sheer",
            2,
            1.0,
            u"Tỷ lệ cao của đường gãy trên phía trong so với chiều cao mạn H."
        ),
        ParameterSpec(
            "upper_chine_keel_follow_factor",
            u"Mức đường gãy trên đi theo sống tàu",
            0.10,
            1.00,
            0.05,
            u"tỷ lệ",
            "Chine and Sheer",
            2,
            1.0,
            u"Điều khiển mức đường gãy trên đi theo độ nâng của sống tàu ở đuôi. Giá trị nhỏ làm upper chine rời vách đuôi êm và phẳng hơn theo chiều dọc."
        ),
        ParameterSpec(
            "upper_chine_outer_height_gap",
            u"Khoảng lệch đứng đường gãy ngoài ΔZ",
            0.00,
            0.30,
            0.01,
            u"m",
            "Chine and Sheer",
            2,
            params.units_per_meter,
            u"Khoảng cách theo phương Z từ đường gãy trên phía trong đến đường gãy trên phía ngoài."
        ),
        ParameterSpec(
            "upper_chine_outer_side_gap",
            u"Khoảng lệch ngang đường gãy ngoài ΔY",
            0.00,
            0.30,
            0.01,
            u"m",
            "Chine and Sheer",
            2,
            params.units_per_meter,
            u"Khoảng cách theo phương ngang Y từ đường gãy trên phía trong ra đường gãy trên phía ngoài."
        ),
        ParameterSpec(
            "sheer_sag_depth_ratio",
            u"Tỷ lệ độ võng mép boong",
            0.00,
            0.12,
            0.005,
            u"tỷ lệ",
            "Chine and Sheer",
            3,
            1.0,
            u"Điều khiển độ võng theo chiều dọc của đường mép boong (sheer)."
        ),
        ParameterSpec(
            "sheer_max_beam_ratio",
            u"Tỷ lệ nửa rộng lớn nhất mép boong",
            0.90,
            1.00,
            0.005,
            u"tỷ lệ",
            "Chine and Sheer",
            3,
            1.0,
            u"Tỷ lệ nửa rộng lớn nhất của đường mép boong so với nửa chiều rộng Bmax/2."
        ),
        ParameterSpec(
            "deadrise_stern_angle",
            u"Góc vát đáy tại đuôi",
            0.0,
            30.0,
            1.0,
            u"độ",
            "Advanced",
            0,
            1.0,
            u"Có thể chỉnh độc lập khi tắt liên kết góc vát đáy mũi/đuôi theo β."
        ),
        ParameterSpec(
            "deadrise_bow_angle",
            u"Góc vát đáy tại mũi",
            0.0,
            30.0,
            1.0,
            u"độ",
            "Advanced",
            0,
            1.0,
            u"Có thể chỉnh độc lập khi tắt liên kết góc vát đáy mũi/đuôi theo β."
        ),
        ParameterSpec(
            "transom_rake_angle",
            u"Góc nghiêng vách đuôi",
            0.0,
            18.0,
            1.0,
            u"độ",
            "Advanced",
            0,
            1.0,
            u"Điều khiển độ nghiêng của vách đuôi. Giá trị mặc định V6.3 là 12 độ để gần dáng mẫu hơn."
        ),
        ParameterSpec(
            "body_station_count",
            u"Số sườn thân",
            3.0,
            15.0,
            1.0,
            u"sườn",
            "Method",
            0,
            1.0,
            u"Số mặt cắt sườn dùng để dựng phần thân chính. Phạm vi V20: 3-15 sườn. Đây là tham số dựng bề mặt, không phải số Station của bản vẽ đường hình."
        ),
        ParameterSpec(
            "bow_fairing_section_count",
            u"Số mặt cắt làm trơn mũi",
            2.0,
            5.0,
            1.0,
            u"mặt cắt",
            "Method",
            0,
            1.0,
            u"Số mặt cắt bổ sung dùng để làm trơn vùng chuyển tiếp về mũi; phạm vi 2-5 mặt cắt."
        )
    ]

UI_PARAMETER_SPECS = build_ui_parameter_specs(PARAMS)



def sync_research_parameters(params):
    if params.link_deadrise_profile:
        params.deadrise_stern_angle = (
            params.deadrise_midship_angle
        )
        params.deadrise_bow_angle = (
            params.deadrise_midship_angle
        )

    params.total_knuckle_count_per_side = int(
        round(
            params.total_knuckle_count_per_side
        )
    )

    params.total_knuckle_count_per_side = max(
        params.knuckle_count_min,
        min(
            params.knuckle_count_max,
            params.total_knuckle_count_per_side
        )
    )


def apply_parameter_bindings(params):
    global PARAMS
    global DERIVED
    global PARAMETER_CATALOG
    global UI_PARAMETER_SPECS
    global ModelVersion
    global GeometryUnitsPerMeter
    global L
    global B
    global H
    global T
    global BaselineZ
    global KeelWidth
    global KeelWidthRatio
    global SternHeightRatio
    global BodyBaseHeightRatio
    global CHeightRatio
    global BowRakeAngle
    global StemTipHeightRatio
    global StemP1AlongRatio
    global StemP1HeightRatio
    global StemP2AlongRatio
    global StemP2HeightRatio
    global StemP3AlongRatio
    global StemP3HeightRatio
    global DeadriseSternAngle
    global DeadriseMidshipAngle
    global DeadriseBowAngle
    global DeadriseMidshipXRatio
    global LowerChineBowEndHeight
    global LowerChineMaxBeamRatio
    global LowerChineSternBeamFactor
    global LowerChineFlare1XRatio
    global LowerChineFlare1BeamFactor
    global LowerChineFlare2XRatio
    global LowerChineFlare2BeamFactor
    global LowerChineFull1XRatio
    global LowerChineFull2XRatio
    global BowBodyStartRatio
    global LowerChineBowStartBeamFactor
    global UpperChineInnerHeightRatio
    global UpperChineInnerMaxBeamRatio
    global UpperChineKeelFollowFactor
    global UpperChineStemJoinHeightRatio
    global UpperChineOuterHeightGap
    global UpperChineOuterSideGap
    global UpperChineGapTaperStart
    global TotalKnuckleCountPerSide
    global SheerMaxBeamRatio
    global SheerSternBeamFactor
    global SheerFlare1BeamFactor
    global SheerFlare2BeamFactor
    global SheerBowStartBeamFactor
    global SheerBowShoulderXRatio
    global SheerBowShoulderBeamFactor
    global SheerSternHeightRatio
    global SheerBowStartHeightRatio
    global SheerSagDepthRatio
    global SheerSagPositionRatio
    global SheerSagShapePower
    global SheerStemJoinHeightRatio
    global SheerBowEntryHandleRatio
    global SheerBowStemHandleRatio
    global SheerBowStemControlOutboardFraction
    global SheerBowStemControlHeightFraction
    global SplitBottomAtKeelStem
    global SplitSidePanelsAtBow
    global UseLongitudinalRailSurfaces
    global BottomTopologyMode
    global BowEntryVerticalTangentScale
    global SheerBowEntryVerticalTangentScale
    global CreateRakedBrokenTransom
    global TransomRakeAngle
    global TransomKeelForwardOffset
    global TransomLowerChineBreakOffset
    global TransomUpperInnerBreakOffset
    global TransomUpperOuterBreakOffset
    global TransomSheerBreakOffset
    global BodyStationCount
    global BowFairingSectionCount
    global MaximumTotalSectionCount
    global UseCosineBodyStationDistribution
    global BowEntryHandleRatio
    global BowStemHandleRatio
    global BowStemControlOutboardFraction
    global BowStemControlHeightFraction
    global LowerSideBodyBulgeRatio
    global LowerSideBowBulgeRatio
    global UpperSideBodyBulgeRatio
    global UpperSideBowBulgeRatio
    global CurveDegree
    global LoftType
    global JoinToleranceFactor
    global LoftRefitTolerance
    global ShowLongitudinalCurves
    global ShowKeelCurve
    global ShowChineCurves
    global ShowSheerCurve
    global ShowBodyStations
    global ShowBowFairingSections
    global ShowDesignPoints
    global ShowTransomFrame
    global CreateHalfModel
    global CreateHullSurfaces
    global CreateTransomSurfaces
    global CreateDeckSurface
    global JoinHullSurfaces
    global AddIndividualSurfacesWhenJoinFails
    global GroupFrameworkOnly
    global ForceSharedLowerChineEdge
    global CreateDesignWaterline
    global ExportParameterTable
    global ExportStationTable
    global DataOutputFolderName

    sync_research_parameters(params)

    PARAMS = params
    DERIVED = DerivedHullData(PARAMS)

    ModelVersion = PARAMS.model_version
    GeometryUnitsPerMeter = PARAMS.units_per_meter

    L = PARAMS.length
    B = PARAMS.beam
    H = PARAMS.depth
    T = PARAMS.draft
    BaselineZ = PARAMS.baseline_z

    KeelWidth = DERIVED.keel_width
    KeelWidthRatio = (
        KeelWidth /
        B
        if B > 0.0
        else 0.0
    )
    PARAMS.keel_width_ratio = KeelWidthRatio

    SternHeightRatio = PARAMS.stern_height_ratio
    BodyBaseHeightRatio = PARAMS.body_base_height_ratio
    CHeightRatio = PARAMS.c_height_ratio

    BowRakeAngle = PARAMS.bow_rake_angle
    StemTipHeightRatio = PARAMS.stem_tip_height_ratio
    StemP1AlongRatio = PARAMS.stem_p1_along_ratio
    StemP1HeightRatio = PARAMS.stem_p1_height_ratio
    StemP2AlongRatio = PARAMS.stem_p2_along_ratio
    StemP2HeightRatio = PARAMS.stem_p2_height_ratio
    StemP3AlongRatio = PARAMS.stem_p3_along_ratio
    StemP3HeightRatio = PARAMS.stem_p3_height_ratio

    DeadriseSternAngle = PARAMS.deadrise_stern_angle
    DeadriseMidshipAngle = PARAMS.deadrise_midship_angle
    DeadriseBowAngle = PARAMS.deadrise_bow_angle
    DeadriseMidshipXRatio = PARAMS.deadrise_midship_x_ratio
    LowerChineBowEndHeight = (
        PARAMS.lower_chine_bow_end_height
    )

    LowerChineMaxBeamRatio = (
        PARAMS.lower_chine_max_beam_ratio
    )
    LowerChineSternBeamFactor = (
        PARAMS.lower_chine_stern_beam_factor
    )
    LowerChineFlare1XRatio = (
        PARAMS.lower_chine_flare1_x_ratio
    )
    LowerChineFlare1BeamFactor = (
        PARAMS.lower_chine_flare1_beam_factor
    )
    LowerChineFlare2XRatio = (
        PARAMS.lower_chine_flare2_x_ratio
    )
    LowerChineFlare2BeamFactor = (
        PARAMS.lower_chine_flare2_beam_factor
    )
    LowerChineFull1XRatio = (
        PARAMS.lower_chine_full1_x_ratio
    )
    LowerChineFull2XRatio = (
        PARAMS.lower_chine_full2_x_ratio
    )
    BowBodyStartRatio = PARAMS.bow_body_start_ratio
    LowerChineBowStartBeamFactor = (
        PARAMS.lower_chine_bow_start_beam_factor
    )

    UpperChineInnerHeightRatio = (
        PARAMS.upper_chine_inner_height_ratio
    )
    UpperChineInnerMaxBeamRatio = (
        PARAMS.upper_chine_inner_max_beam_ratio
    )
    UpperChineKeelFollowFactor = (
        PARAMS.upper_chine_keel_follow_factor
    )
    UpperChineStemJoinHeightRatio = (
        PARAMS.upper_chine_stem_join_height_ratio
    )
    UpperChineOuterHeightGap = (
        PARAMS.upper_chine_outer_height_gap
    )
    UpperChineOuterSideGap = (
        PARAMS.upper_chine_outer_side_gap
    )
    UpperChineGapTaperStart = (
        PARAMS.upper_chine_gap_taper_start
    )

    TotalKnuckleCountPerSide = (
        PARAMS.total_knuckle_count_per_side
    )

    SheerMaxBeamRatio = PARAMS.sheer_max_beam_ratio
    SheerSternBeamFactor = PARAMS.sheer_stern_beam_factor
    SheerFlare1BeamFactor = PARAMS.sheer_flare1_beam_factor
    SheerFlare2BeamFactor = PARAMS.sheer_flare2_beam_factor
    SheerBowStartBeamFactor = (
        PARAMS.sheer_bow_start_beam_factor
    )
    SheerBowShoulderXRatio = (
        PARAMS.sheer_bow_shoulder_x_ratio
    )
    SheerBowShoulderBeamFactor = (
        PARAMS.sheer_bow_shoulder_beam_factor
    )
    SheerSternHeightRatio = PARAMS.sheer_stern_height_ratio
    SheerBowStartHeightRatio = (
        PARAMS.sheer_bow_start_height_ratio
    )
    SheerSagDepthRatio = PARAMS.sheer_sag_depth_ratio
    SheerSagPositionRatio = PARAMS.sheer_sag_position_ratio
    SheerSagShapePower = PARAMS.sheer_sag_shape_power
    SheerStemJoinHeightRatio = (
        PARAMS.sheer_stem_join_height_ratio
    )

    SheerBowEntryHandleRatio = (
        PARAMS.sheer_bow_entry_handle_ratio
    )
    SheerBowStemHandleRatio = (
        PARAMS.sheer_bow_stem_handle_ratio
    )
    SheerBowStemControlOutboardFraction = (
        PARAMS.sheer_bow_stem_control_outboard_fraction
    )
    SheerBowStemControlHeightFraction = (
        PARAMS.sheer_bow_stem_control_height_fraction
    )

    SplitBottomAtKeelStem = (
        PARAMS.split_bottom_at_keel_stem
    )
    SplitSidePanelsAtBow = PARAMS.split_side_panels_at_bow

    UseLongitudinalRailSurfaces = (
        PARAMS.use_longitudinal_rail_surfaces
    )

    BottomTopologyMode = PARAMS.bottom_topology_mode
    BowEntryVerticalTangentScale = (
        PARAMS.bow_entry_vertical_tangent_scale
    )
    SheerBowEntryVerticalTangentScale = (
        PARAMS.sheer_bow_entry_vertical_tangent_scale
    )

    CreateRakedBrokenTransom = (
        PARAMS.create_raked_broken_transom
    )
    TransomRakeAngle = PARAMS.transom_rake_angle
    TransomKeelForwardOffset = (
        PARAMS.transom_keel_forward_offset
    )
    TransomLowerChineBreakOffset = (
        PARAMS.transom_lower_chine_break_offset
    )
    TransomUpperInnerBreakOffset = (
        PARAMS.transom_upper_inner_break_offset
    )
    TransomUpperOuterBreakOffset = (
        PARAMS.transom_upper_outer_break_offset
    )
    TransomSheerBreakOffset = (
        PARAMS.transom_sheer_break_offset
    )

    BodyStationCount = PARAMS.body_station_count
    BowFairingSectionCount = (
        PARAMS.bow_fairing_section_count
    )
    MaximumTotalSectionCount = (
        PARAMS.maximum_total_section_count
    )
    UseCosineBodyStationDistribution = (
        PARAMS.use_cosine_body_station_distribution
    )

    BowEntryHandleRatio = PARAMS.bow_entry_handle_ratio
    BowStemHandleRatio = PARAMS.bow_stem_handle_ratio
    BowStemControlOutboardFraction = (
        PARAMS.bow_stem_control_outboard_fraction
    )
    BowStemControlHeightFraction = (
        PARAMS.bow_stem_control_height_fraction
    )

    LowerSideBodyBulgeRatio = (
        PARAMS.lower_side_body_bulge_ratio
    )
    LowerSideBowBulgeRatio = (
        PARAMS.lower_side_bow_bulge_ratio
    )
    UpperSideBodyBulgeRatio = (
        PARAMS.upper_side_body_bulge_ratio
    )
    UpperSideBowBulgeRatio = (
        PARAMS.upper_side_bow_bulge_ratio
    )

    CurveDegree = PARAMS.curve_degree
    LoftType = PARAMS.loft_type
    JoinToleranceFactor = PARAMS.join_tolerance_factor
    LoftRefitTolerance = PARAMS.loft_refit_tolerance

    ShowKeelCurve = bool(
        getattr(
            PARAMS,
            "show_keel_curve",
            PARAMS.show_longitudinal_curves
        )
    )
    ShowChineCurves = bool(
        getattr(
            PARAMS,
            "show_chine_curves",
            PARAMS.show_longitudinal_curves
        )
    )
    ShowSheerCurve = bool(
        getattr(
            PARAMS,
            "show_sheer_curve",
            PARAMS.show_longitudinal_curves
        )
    )

    ShowLongitudinalCurves = bool(
        ShowKeelCurve or
        ShowChineCurves or
        ShowSheerCurve
    )

    ShowBodyStations = PARAMS.show_body_stations
    ShowBowFairingSections = PARAMS.show_bow_fairing_sections
    ShowDesignPoints = PARAMS.show_design_points
    ShowTransomFrame = bool(
        getattr(
            PARAMS,
            "show_transom_frame",
            True
        )
    )
    CreateHalfModel = bool(
        getattr(
            PARAMS,
            "create_half_model",
            False
        )
    )

    CreateHullSurfaces = PARAMS.create_hull_surfaces
    CreateTransomSurfaces = PARAMS.create_transom_surfaces
    CreateDeckSurface = PARAMS.create_deck_surface
    JoinHullSurfaces = PARAMS.join_hull_surfaces
    AddIndividualSurfacesWhenJoinFails = (
        PARAMS.add_individual_surfaces_when_join_fails
    )

    GroupFrameworkOnly = (
        PARAMS.group_framework_only
    )

    ForceSharedLowerChineEdge = (
        PARAMS.force_shared_lower_chine_edge
    )
    CreateDesignWaterline = PARAMS.create_design_waterline

    ExportParameterTable = PARAMS.export_parameter_table
    ExportStationTable = PARAMS.export_station_table
    DataOutputFolderName = PARAMS.data_output_folder_name


    PARAMETER_CATALOG = build_parameter_catalog(PARAMS)
    UI_PARAMETER_SPECS = build_ui_parameter_specs(PARAMS)


# MODULE 4: CÁC HÀM TOÁN HỌC VÀ HÌNH HỌC HỖ TRỢ
# Nhiệm vụ: chứa các hàm nội suy, clamp, smootherstep, xử lý curve/point và
# các thao tác hình học dùng lặp lại ở nhiều module dựng thân.

def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))

def lerp(value_a, value_b, parameter):
    return value_a * (1.0 - parameter) + value_b * parameter

def smootherstep(value):
    value = clamp(value, 0.0, 1.0)
    return value * value * value * (
        value * (value * 6.0 - 15.0) + 10.0
    )

def lerp_point(point_a, point_b, parameter):
    return rg.Point3d(
        lerp(point_a.X, point_b.X, parameter),
        lerp(point_a.Y, point_b.Y, parameter),
        lerp(point_a.Z, point_b.Z, parameter)
    )

def cubic_bezier_point(point_0, point_1, point_2, point_3, parameter):
    one_minus = 1.0 - parameter
    weight_0 = one_minus * one_minus * one_minus
    weight_1 = 3.0 * one_minus * one_minus * parameter
    weight_2 = 3.0 * one_minus * parameter * parameter
    weight_3 = parameter * parameter * parameter

    return rg.Point3d(
        point_0.X * weight_0 +
        point_1.X * weight_1 +
        point_2.X * weight_2 +
        point_3.X * weight_3,
        point_0.Y * weight_0 +
        point_1.Y * weight_1 +
        point_2.Y * weight_2 +
        point_3.Y * weight_3,
        point_0.Z * weight_0 +
        point_1.Z * weight_1 +
        point_2.Z * weight_2 +
        point_3.Z * weight_3
    )

# =============================================================================
                                                             
# =============================================================================
# Mục đích:
# - Layer "khung" chỉ giữ các đường/điểm phục vụ dựng và kiểm tra hình học.
# - Keel, Chine, Sheer được tách sang MODEL112::HULL_LINES để phục vụ bản vẽ 2D.
# - Các đối tượng dạng mặt của vỏ tàu
#   (surface, polysurface, Brep, các panel vỏ, transom, ...)
#   được đưa vào layer: "mặt tàu".
# - Nếu layer chưa tồn tại, chương trình tự tạo layer trước khi thêm đối tượng.
# - Việc gán layer được thực hiện ngay tại thời điểm đối tượng được Add vào Rhino,
#   vì vậy không cần quét và phân loại lại toàn bộ mô hình sau khi dựng.

LAYER_KHUNG = u"khung"
LAYER_MAT_TAU = u"mặt tàu"

# Đường đặc trưng thân tàu được tách khỏi "khung" để phục vụ bản vẽ 2D.
LAYER_HULL_LINES_ROOT = u"MODEL112::HULL_LINES"
LAYER_HULL_KEEL = LAYER_HULL_LINES_ROOT + u"::Keel"
LAYER_HULL_CHINES = LAYER_HULL_LINES_ROOT + u"::Chines"
LAYER_HULL_SHEER = LAYER_HULL_LINES_ROOT + u"::Sheer"

# Toàn bộ đường khung vách đuôi dùng chung một layer duy nhất.
LAYER_TRANSOM_FRAME = LAYER_HULL_LINES_ROOT + u"::TransomFrame"


def ensure_model_layer_path(layer_path):
    """
    Tạo layer hoặc cây layer Rhino từ đường dẫn Parent::Child::SubChild.
    """
    if not layer_path:
        return -1

    parts = [
        part.strip()
        for part in str(layer_path).split("::")
        if part.strip()
    ]

    if not parts:
        return -1

    parent_id = System.Guid.Empty
    current_parts = []

    for part in parts:
        current_parts.append(part)
        full_path = "::".join(current_parts)

        try:
            layer_index = sc.doc.Layers.FindByFullPath(
                full_path,
                -1
            )
        except Exception:
            layer_index = -1

        if layer_index is None or layer_index < 0:
            new_layer = Rhino.DocObjects.Layer()
            new_layer.Name = part

            if parent_id != System.Guid.Empty:
                new_layer.ParentLayerId = parent_id

            try:
                layer_index = sc.doc.Layers.Add(
                    new_layer
                )
            except Exception as error:
                print(
                    u"Không thể tạo layer '{}': {}".format(
                        full_path,
                        error
                    )
                )
                return -1

        if layer_index is None or layer_index < 0:
            return -1

        try:
            parent_id = sc.doc.Layers[
                layer_index
            ].Id
        except Exception:
            parent_id = System.Guid.Empty

    return layer_index


def get_layer_attributes(layer_name):
    """
    Tìm hoặc tự tạo layer, hỗ trợ cả cây layer dùng ký hiệu ::.
    """
    layer_index = ensure_model_layer_path(
        layer_name
    )

    if layer_index is None or layer_index < 0:
        return None

    attributes = Rhino.DocObjects.ObjectAttributes()
    attributes.LayerIndex = layer_index
    return attributes


CURRENT_CREATED_IDS = []


def track_created_id(object_id):
    if (
        object_id is not None and
        object_id != System.Guid.Empty
    ):
        CURRENT_CREATED_IDS.append(
            object_id
        )

    return object_id


def add_curve(curve):
    # Curve dựng hình thông thường vào layer "khung"; Keel/Chine/Sheer dùng layer riêng.
    if curve is None:
        return None

    attributes = get_layer_attributes(
        LAYER_KHUNG
    )

    if attributes is not None:
        object_id = sc.doc.Objects.AddCurve(
            curve,
            attributes
        )
    else:
        # Fallback: vẫn tạo đối tượng nếu việc tạo layer thất bại.
        object_id = sc.doc.Objects.AddCurve(
            curve
        )

    return track_created_id(object_id)


def add_curve_on_layer(
    curve,
    layer_name
):
    """
    Add Curve vào layer cụ thể và vẫn theo dõi GUID trong CURRENT_CREATED_IDS.
    """
    if curve is None:
        return None

    attributes = get_layer_attributes(
        layer_name
    )

    if attributes is not None:
        object_id = sc.doc.Objects.AddCurve(
            curve,
            attributes
        )
    else:
        object_id = sc.doc.Objects.AddCurve(
            curve
        )

    return track_created_id(
        object_id
    )


def set_objects_hidden(
    object_ids,
    hidden_state
):
    for object_id in object_ids or []:
        try:
            if hidden_state:
                sc.doc.Objects.Hide(
                    object_id,
                    True
                )
            else:
                sc.doc.Objects.Show(
                    object_id,
                    True
                )
        except Exception:
            pass


def hide_visible_model112_objects_temporarily(object_ids):
    """Chỉ ẩn các đối tượng đang thấy; trả ID để khôi phục đúng trạng thái."""
    hidden_ids = []
    for object_id in object_ids or []:
        try:
            rhino_object = sc.doc.Objects.FindId(object_id)
            if rhino_object is None or not rhino_object.Visible:
                continue
            if sc.doc.Objects.Hide(object_id, False):
                hidden_ids.append(object_id)
        except Exception:
            continue
    return hidden_ids


def restore_temporarily_hidden_model112_objects(object_ids):
    """Không bật lại đường người dùng đã tự ẩn hoặc layer đang tắt."""
    for object_id in object_ids or []:
        try:
            rhino_object = sc.doc.Objects.FindId(object_id)
            if rhino_object is not None and rhino_object.IsHidden:
                sc.doc.Objects.Show(object_id, False)
        except Exception:
            pass


def add_point(point):
    # Điểm thiết kế/control point cũng được xem là một phần của "khung".
    attributes = get_layer_attributes(
        LAYER_KHUNG
    )

    if attributes is not None:
        object_id = sc.doc.Objects.AddPoint(
            point,
            attributes
        )
    else:
        object_id = sc.doc.Objects.AddPoint(
            point
        )

    return track_created_id(object_id)


def add_brep(brep):
    # Surface/Polysurface/Brep của vỏ tàu được đưa vào layer "mặt tàu".
    if brep is None:
        return None

    attributes = get_layer_attributes(
        LAYER_MAT_TAU
    )

    if attributes is not None:
        object_id = sc.doc.Objects.AddBrep(
            brep,
            attributes
        )
    else:
        # Fallback: vẫn tạo bề mặt nếu việc tạo layer thất bại.
        object_id = sc.doc.Objects.AddBrep(
            brep
        )

    return track_created_id(object_id)

def create_control_curve(points, degree):
    if points is None or len(points) < degree + 1:
        return None
    return rg.Curve.CreateControlPointCurve(points, degree)

def create_interp_curve(points, degree):
    if points is None or len(points) < degree + 1:
        return None
    return rg.Curve.CreateInterpolatedCurve(points, degree)

def join_two_curves(curve_a, curve_b):
    if curve_a is None or curve_b is None:
        return None

    result = rg.Curve.JoinCurves(
        [curve_a, curve_b],
        sc.doc.ModelAbsoluteTolerance
    )

    if result and len(result) > 0:
        return result[0]

    return None

def point_at_normalized_length(curve, normalized_length):
    normalized_length = clamp(normalized_length, 0.0, 1.0)

    success, parameter = curve.NormalizedLengthParameter(
        normalized_length
    )

    if not success:
        parameter = curve.Domain.ParameterAt(
            normalized_length
        )

    return curve.PointAt(parameter)

def point_on_curve_at_z(curve, target_z):
    domain = curve.Domain
    parameter_0 = domain.T0
    parameter_1 = domain.T1

    start_point = curve.PointAt(parameter_0)
    end_point = curve.PointAt(parameter_1)

    target_z = clamp(
        target_z,
        min(start_point.Z, end_point.Z),
        max(start_point.Z, end_point.Z)
    )

    increasing = end_point.Z >= start_point.Z

    for index in range(90):
        middle_parameter = (
            parameter_0 +
            parameter_1
        ) * 0.5

        middle_point = curve.PointAt(
            middle_parameter
        )

        if increasing:
            if middle_point.Z < target_z:
                parameter_0 = middle_parameter
            else:
                parameter_1 = middle_parameter
        else:
            if middle_point.Z > target_z:
                parameter_0 = middle_parameter
            else:
                parameter_1 = middle_parameter

    return curve.PointAt(
        (
            parameter_0 +
            parameter_1
        ) * 0.5
    )

def point_on_curve_at_x(curve, target_x):
    domain = curve.Domain
    parameter_0 = domain.T0
    parameter_1 = domain.T1

    start_point = curve.PointAt(parameter_0)
    end_point = curve.PointAt(parameter_1)

    target_x = clamp(
        target_x,
        min(start_point.X, end_point.X),
        max(start_point.X, end_point.X)
    )

    increasing = end_point.X >= start_point.X

    for index in range(90):
        middle_parameter = (
            parameter_0 +
            parameter_1
        ) * 0.5

        middle_point = curve.PointAt(
            middle_parameter
        )

        if increasing:
            if middle_point.X < target_x:
                parameter_0 = middle_parameter
            else:
                parameter_1 = middle_parameter
        else:
            if middle_point.X > target_x:
                parameter_0 = middle_parameter
            else:
                parameter_1 = middle_parameter

    return curve.PointAt(
        (
            parameter_0 +
            parameter_1
        ) * 0.5
    )

def design_waterline_z():
    return DERIVED.waterline_z

# MODULE 5: TẠO SỐNG TÀU VÀ SỐNG MŨI
# Nhiệm vụ: xác định hình học keel body, forefoot và stem dựa trên L, H,
# bow-rake alpha cùng các tỷ lệ hình dáng đã khai báo.

def get_stem_dimensions():
    return (
        DERIVED.stem_start_x,
        DERIVED.stem_start_z,
        DERIVED.stem_tip_z,
        DERIVED.stem_horizontal_run
    )

def stem_start_ratio():
    return DERIVED.stem_start_ratio

def keel_reference_height(x_ratio):
    stern_blend_end = 0.48
    body_flat_end = 0.78
    c_ratio = stem_start_ratio()

    stern_z = H * SternHeightRatio
    base_z = H * BodyBaseHeightRatio
    c_z = H * CHeightRatio

    if x_ratio <= stern_blend_end:
        blend = smootherstep(
            x_ratio /
            stern_blend_end
        )

        return lerp(
            stern_z,
            base_z,
            blend
        )

    if x_ratio <= body_flat_end:
        return base_z

    if x_ratio <= c_ratio:
        denominator = (
            c_ratio -
            body_flat_end
        )

        if denominator <= 0.0:
            return c_z

        blend = smootherstep(
            (
                x_ratio -
                body_flat_end
            ) /
            denominator
        )

        return lerp(
            base_z,
            c_z,
            blend
        )

    return c_z

def create_body_keel_points(y_value):
    c_ratio = stem_start_ratio()

    pre_c_ratio = clamp(
        c_ratio - 0.06,
        0.75,
        0.84
    )

    shoulder_ratio = min(
        0.72,
        pre_c_ratio - 0.04
    )

    # -------------------------------------------------------------------------
                                                        
    # -------------------------------------------------------------------------
    # Trước đây đường keel luôn bắt đầu tại X = 0. Khi tăng góc nghiêng vách
    # đuôi, mặt transom dịch về phía trước ở đáy nhưng keel vẫn kéo dài về X=0,
    # vì vậy xuất hiện một đoạn keel thừa phía sau vách đuôi.
    #
                                                                               
    # vách đuôi. Góc transom = 0 độ thì keel vẫn bắt đầu tại X=0. Góc transom
    # càng lớn thì keel được cắt ngắn tương ứng và luôn kết thúc đúng tại vách.
    keel_start_x = transom_keel_cut_x()
    keel_start_ratio = clamp(
        keel_start_x / L,
        0.0,
        c_ratio
    )

    # Các điểm điều khiển còn lại giữ nguyên phân bố hình học cũ. Nếu trong
    # tương lai vị trí cắt keel vượt qua một điểm điều khiển, điểm đó sẽ được bỏ
    # qua để bảo đảm thứ tự X luôn tăng và đường cong không bị đảo chiều.
    candidate_ratios = [
        0.12,
        0.28,
        0.50,
        shoulder_ratio,
        pre_c_ratio,
        c_ratio
    ]

    x_ratios = [
        keel_start_ratio
    ]

    for candidate_ratio in candidate_ratios:
        if (
            candidate_ratio >
            keel_start_ratio + 1.0e-9
        ):
            x_ratios.append(
                candidate_ratio
            )

    if (
        x_ratios[-1] <
        c_ratio - 1.0e-9
    ):
        x_ratios.append(
            c_ratio
        )

    points = []

    for x_ratio in x_ratios:
        points.append(
            rg.Point3d(
                L * x_ratio,
                y_value,
                keel_reference_height(
                    x_ratio
                )
            )
        )

    points[-1] = rg.Point3d(
        L * c_ratio,
        y_value,
        H * CHeightRatio
    )

    return points

def create_stem_points(y_value):
    c_x, c_z, tip_z, stem_length_x = (
        get_stem_dimensions()
    )

    return [
        rg.Point3d(
            c_x,
            y_value,
            c_z
        ),
        rg.Point3d(
            c_x +
            stem_length_x *
            StemP1AlongRatio,
            y_value,
            H *
            StemP1HeightRatio
        ),
        rg.Point3d(
            c_x +
            stem_length_x *
            StemP2AlongRatio,
            y_value,
            H *
            StemP2HeightRatio
        ),
        rg.Point3d(
            c_x +
            stem_length_x *
            StemP3AlongRatio,
            y_value,
            H *
            StemP3HeightRatio
        ),
        rg.Point3d(
            L,
            y_value,
            tip_z
        )
    ]

def create_keel_side(y_value):
    body_points = create_body_keel_points(
        y_value
    )

    stem_points = create_stem_points(
        y_value
    )

    body_curve = create_interp_curve(
        body_points,
        CurveDegree
    )

    stem_curve = create_control_curve(
        stem_points,
        CurveDegree
    )

    joined_curve = join_two_curves(
        body_curve,
        stem_curve
    )

    return (
        body_curve,
        stem_curve,
        joined_curve,
        body_points,
        stem_points
    )

def piecewise_factor(x_ratio, controls):
    if x_ratio <= controls[0][0]:
        return controls[0][1]

    for index in range(
        len(controls) - 1
    ):
        x_0, value_0 = controls[index]
        x_1, value_1 = controls[index + 1]

        if x_ratio <= x_1:
            denominator = x_1 - x_0

            if denominator <= 0.0:
                return value_1

            local_parameter = (
                x_ratio -
                x_0
            ) / denominator

            blend = smootherstep(
                local_parameter
            )

            return lerp(
                value_0,
                value_1,
                blend
            )

    return controls[-1][1]

def lower_chine_beam_factor(x_ratio):
    controls = [
        (
            0.00,
            LowerChineSternBeamFactor
        ),
        (
            LowerChineFlare1XRatio,
            LowerChineFlare1BeamFactor
        ),
        (
            LowerChineFlare2XRatio,
            LowerChineFlare2BeamFactor
        ),
        (
            LowerChineFull1XRatio,
            1.00
        ),
        (
            LowerChineFull2XRatio,
            1.00
        ),
        (
            BowBodyStartRatio,
            LowerChineBowStartBeamFactor
        )
    ]

    return piecewise_factor(
        x_ratio,
        controls
    )

def sheer_beam_factor(x_ratio):
    controls = [
        (0.00, SheerSternBeamFactor),
        (
            LowerChineFlare1XRatio,
            SheerFlare1BeamFactor
        ),
        (
            LowerChineFlare2XRatio,
            SheerFlare2BeamFactor
        ),
        (
            LowerChineFull1XRatio,
            1.00
        ),
        (
            SheerBowShoulderXRatio,
            SheerBowShoulderBeamFactor
        ),
        (
            BowBodyStartRatio,
            SheerBowStartBeamFactor
        )
    ]

    return piecewise_factor(
        x_ratio,
        controls
    )

def deadrise_at_x(x_ratio):
    x_ratio = clamp(
        x_ratio,
        0.0,
        BowBodyStartRatio
    )

    if x_ratio <= DeadriseMidshipXRatio:
        blend = smootherstep(
            x_ratio /
            DeadriseMidshipXRatio
        )

        return lerp(
            DeadriseSternAngle,
            DeadriseMidshipAngle,
            blend
        )

    denominator = (
        BowBodyStartRatio -
        DeadriseMidshipXRatio
    )

    if denominator <= 0.0:
        return DeadriseBowAngle

    blend = smootherstep(
        (
            x_ratio -
            DeadriseMidshipXRatio
        ) /
        denominator
    )

    return lerp(
        DeadriseMidshipAngle,
        DeadriseBowAngle,
        blend
    )

# MODULE 6: TẠO CÁC ĐƯỜNG CHINE
# Nhiệm vụ: tạo lower chine, upper inner chine, upper outer chine và các
# quan hệ hình học giữa chine với sống tàu, mũi và mặt cắt.

def lower_chine_body_point(
    side_sign,
    x_ratio,
    half_keel_width
):
    half_beam = B * 0.5

    y_absolute = (
        half_beam *
        LowerChineMaxBeamRatio *
        lower_chine_beam_factor(
            x_ratio
        )
    )

    horizontal_run = max(
        0.0,
        y_absolute -
        half_keel_width
    )

    z_value = (
        keel_reference_height(
            x_ratio
        ) +
        horizontal_run *
        math.tan(
            math.radians(
                deadrise_at_x(
                    x_ratio
                )
            )
        )
    )

    return rg.Point3d(
        L * x_ratio,
        side_sign * y_absolute,
        z_value
    )

def upper_chine_inner_body_point(
    side_sign,
    x_ratio
):
    half_beam = B * 0.5

    y_absolute = (
        half_beam *
        UpperChineInnerMaxBeamRatio *
        lower_chine_beam_factor(
            x_ratio
        )
    )

                                                                      
    # Mặc định 0.35 giúp đường upper chine không tụt quá nhanh sau vách đuôi.
    # giữ tiếp tuyến dọc thân êm, gần đường nét của mẫu tham chiếu.
    z_value = (
        keel_reference_height(
            x_ratio
        ) *
        UpperChineKeelFollowFactor +
        H *
        UpperChineInnerHeightRatio
    )

    return rg.Point3d(
        L * x_ratio,
        side_sign * y_absolute,
        z_value
    )

def upper_chine_outer_body_point(
    inner_point,
    side_sign
):
    return rg.Point3d(
        inner_point.X,
        inner_point.Y +
        side_sign *
        UpperChineOuterSideGap,
        inner_point.Z +
        UpperChineOuterHeightGap
    )

def transom_keel_cut_x():
    # -------------------------------------------------------------------------
    # MODULE HỖ TRỢ VÁCH ĐUÔI - TÍNH GIAO ĐIỂM VỚI KEEL
    # -------------------------------------------------------------------------
    # Quy ước của Model 112:
    # - Mép sheer của vách đuôi được neo tại X = 0.
    # - Vách đuôi nghiêng về phía trước khi đi xuống đáy.
    # - Vì keel có độ cong theo X nên vị trí cắt được giải lặp vài lần để giao
    #   điểm bám đúng đường keel chứ không dùng một offset cố định.
    #
    # Kết quả là Transom rake = 0 độ -> X cắt keel = 0.
    # Khi tăng góc transom, X cắt keel tự tăng theo hình học thực tế.
    if not CreateRakedBrokenTransom:
        return 0.0

    rake_tangent = math.tan(
        math.radians(
            TransomRakeAngle
        )
    )

    if abs(rake_tangent) <= 1.0e-12:
        return 0.0

    # Sheer tại đuôi là điểm neo của mặt transom ở X = 0.
    reference_sheer_z = sheer_height(
        0.0
    )

    cut_x = 0.0

    # Giải lặp giao điểm vì cao độ keel thay đổi nhẹ theo chiều X.
    for iteration_index in range(20):
        x_ratio = clamp(
            cut_x / L,
            0.0,
            stem_start_ratio()
        )

        local_keel_z = keel_reference_height(
            x_ratio
        )

        new_cut_x = max(
            0.0,
            (
                reference_sheer_z -
                local_keel_z
            ) *
            rake_tangent -
            TransomSheerBreakOffset
        )

        new_cut_x = clamp(
            new_cut_x,
            0.0,
            L * 0.10
        )

        if abs(new_cut_x - cut_x) <= 0.001:
            cut_x = new_cut_x
            break

        cut_x = new_cut_x

    return cut_x


def transom_level_x(
    level_name,
    level_z,
    keel_z
):
    if not CreateRakedBrokenTransom:
        return 0.0

    break_offset = 0.0

    if level_name == "lower":
        break_offset = (
            TransomLowerChineBreakOffset
        )
    elif level_name == "upper_inner":
        break_offset = (
            TransomUpperInnerBreakOffset
        )
    elif level_name == "upper_outer":
        break_offset = (
            TransomUpperOuterBreakOffset
        )
    elif level_name == "sheer":
        break_offset = (
            TransomSheerBreakOffset
        )

    vertical_rise = max(
        0.0,
        level_z -
        keel_z
    )

    rake_run = (
        vertical_rise *
        math.tan(
            math.radians(
                TransomRakeAngle
            )
        )
    )

               
    # Không dùng TransomKeelForwardOffset cố định nữa. Vị trí keel tại vách đuôi
    # được tính trực tiếp từ góc rake, nhờ đó thay đổi 1 độ, 2 độ... đều làm
    # keel tự cắt theo vách và không còn phần keel nhô ra phía sau.
    automatic_keel_forward_offset = (
        transom_keel_cut_x()
    )

    return max(
        0.0,
        automatic_keel_forward_offset -
        rake_run +
        break_offset
    )

# MODULE 7: TẠO ĐƯỜNG SHEER
# Nhiệm vụ: xác định đường mép mạn/sheer theo chiều dọc thân và làm fair
# vùng vai mũi để giữ hình dáng tàu cá đã được chấp nhận ở các phiên bản trước.

def sheer_height(x_ratio):
    # ---------------------------------------------------------------------
                                            
    # ---------------------------------------------------------------------
    # Bản cũ tạo độ võng bằng sin/cos. Dù liên tục, độ cong tập trung khá
    # sớm sau vách đuôi nên nhìn ở hình chiếu cạnh đường sheer bị "gục"
    # xuống nhanh rồi mới phẳng lại.
    #
                                          
    #   1) Từ vách đuôi -> điểm võng thấp nhất.
    #   2) Từ điểm võng thấp nhất -> vùng bắt đầu mũi.
    #
    # Mỗi nhánh dùng smootherstep (C2), vì vậy tại vách đuôi, tại đáy võng
    # và tại đầu vùng mũi đều có chuyển tiếp rất êm, không tạo gãy độ cong.
    local_x = clamp(
        x_ratio / BowBodyStartRatio,
        0.0,
        1.0
    )

    stern_z = (
        H *
        SheerSternHeightRatio
    )

    bow_z = (
        H *
        SheerBowStartHeightRatio
    )

    sag_position = clamp(
        SheerSagPositionRatio,
        0.20,
        0.80
    )

    sag_depth = (
        H *
        SheerSagDepthRatio
    )

    # Cao độ đường thẳng nối đuôi - đầu mũi tại vị trí võng.
    reference_mid_z = lerp(
        stern_z,
        bow_z,
        sag_position
    )

    # Điểm thấp nhất thực của sheer.
    sag_z = (
        reference_mid_z -
        sag_depth
    )

    if local_x <= sag_position:
        denominator = max(
            sag_position,
            1.0e-9
        )

        local_parameter = (
            local_x /
            denominator
        )

        blend = smootherstep(
            local_parameter
        )

        return lerp(
            stern_z,
            sag_z,
            blend
        )

    denominator = max(
        1.0 - sag_position,
        1.0e-9
    )

    local_parameter = (
        local_x -
        sag_position
    ) / denominator

    blend = smootherstep(
        local_parameter
    )

    return lerp(
        sag_z,
        bow_z,
        blend
    )


def sheer_body_point(
    side_sign,
    x_ratio
):
    half_beam = B * 0.5

    y_absolute = (
        half_beam *
        SheerMaxBeamRatio *
        sheer_beam_factor(
            x_ratio
        )
    )

    return rg.Point3d(
        L * x_ratio,
        side_sign * y_absolute,
        sheer_height(
            x_ratio
        )
    )

# MODULE 8: TẠO CÁC MẶT CẮT SƯỜN / STATION
# Nhiệm vụ: phân bố station thân và các section fairing mũi, sau đó tạo
# đường mặt cắt qua keel - chine - sheer phục vụ loft bề mặt.

def create_body_station_ratios():
    count = int(
        BodyStationCount
    )

    ratios = []

    for index in range(count):
        local_parameter = (
            float(index) /
            float(count - 1)
        )

        if UseCosineBodyStationDistribution:
            distribution = (
                0.5 -
                0.5 *
                math.cos(
                    math.pi *
                    local_parameter
                )
            )
        else:
            distribution = (
                local_parameter
            )

        ratios.append(
            BowBodyStartRatio *
            distribution
        )

    ratios[0] = 0.0
    ratios[-1] = (
        BowBodyStartRatio
    )

    return ratios

def create_bow_progress_values():
    count = int(
        BowFairingSectionCount
    )

    values = []

    for index in range(count):
        values.append(
            float(index + 1) /
            float(count + 1)
        )

    return values

def create_bow_bezier_points(
    body_points,
    stem_join_point,
    bow_progress_values,
    vertical_fraction,
    entry_handle_ratio=None,
    stem_handle_ratio=None,
    stem_control_outboard_fraction=None,
    stem_control_height_fraction=None,
    vertical_tangent_scale=None
):
    point_0 = body_points[-1]

    if entry_handle_ratio is None:
        entry_handle_ratio = BowEntryHandleRatio

    if stem_handle_ratio is None:
        stem_handle_ratio = BowStemHandleRatio

    if stem_control_outboard_fraction is None:
        stem_control_outboard_fraction = (
            BowStemControlOutboardFraction
        )

    if stem_control_height_fraction is None:
        stem_control_height_fraction = (
            BowStemControlHeightFraction
        )

    if vertical_tangent_scale is None:
        vertical_tangent_scale = (
            BowEntryVerticalTangentScale
        )

    tangent_reference_index = max(
        0,
        len(body_points) - 3
    )

    tangent = (
        point_0 -
        body_points[tangent_reference_index]
    )

    tangent.Z *= (
        vertical_tangent_scale
    )

    if not tangent.Unitize():
        tangent = (
            rg.Vector3d.XAxis
        )

    if tangent.X < 0.0:
        tangent.Reverse()

    entry_length = (
        L *
        entry_handle_ratio *
        (
            1.0 -
            0.08 *
            vertical_fraction
        )
    )

    stem_length = (
        L *
        stem_handle_ratio *
        (
            1.0 +
            0.08 *
            vertical_fraction
        )
    )

    point_1 = (
        point_0 +
        tangent *
        entry_length
    )

    point_2 = rg.Point3d(
        stem_join_point.X -
        stem_length,
        lerp(
            stem_join_point.Y,
            point_0.Y,
            stem_control_outboard_fraction
        ),
        lerp(
            stem_join_point.Z,
            point_0.Z,
            stem_control_height_fraction
        )
    )

    minimum_gap = (
        L *
        0.012
    )

    point_1.X = clamp(
        point_1.X,
        point_0.X +
        minimum_gap,
        stem_join_point.X -
        minimum_gap *
        2.0
    )

    point_2.X = clamp(
        point_2.X,
        point_1.X +
        minimum_gap,
        stem_join_point.X -
        minimum_gap
    )

    bow_curve = (
        rg.Curve.CreateControlPointCurve(
            [
                point_0,
                point_1,
                point_2,
                stem_join_point
            ],
            3
        )
    )

    if bow_curve is None:
        raise Exception(
            "Could not create bow control curve."
        )

    points = list(
        body_points
    )

    for bow_progress in bow_progress_values:
        points.append(
            point_at_normalized_length(
                bow_curve,
                bow_progress
            )
        )

    points.append(
        stem_join_point
    )

    return points

def create_exact_curve_bow_points(
    exact_curve,
    body_points,
    end_point,
    bow_progress_values
):
    start_point = body_points[-1]

    success_start, start_parameter = (
        exact_curve.ClosestPoint(
            start_point
        )
    )

    success_end, end_parameter = (
        exact_curve.ClosestPoint(
            end_point
        )
    )

    if (
        not success_start or
        not success_end
    ):
        raise Exception(
            "Could not locate the keel bow interval."
        )

    if end_parameter < start_parameter:
        temporary = start_parameter
        start_parameter = end_parameter
        end_parameter = temporary

    trimmed_curve = exact_curve.Trim(
        start_parameter,
        end_parameter
    )

    if trimmed_curve is None:
        raise Exception(
            "Could not trim the keel bow interval."
        )

    points = list(
        body_points
    )

    for bow_progress in bow_progress_values:
        points.append(
            point_at_normalized_length(
                trimmed_curve,
                bow_progress
            )
        )

    points.append(
        end_point
    )

    return points

def create_upper_outer_points(
    inner_points,
    side_sign,
    body_station_count,
    bow_progress_values,
    body_outer_points=None
):
    points = []

    for index in range(
        body_station_count
    ):
        if body_outer_points is not None:
            points.append(
                body_outer_points[index]
            )
        else:
            inner_point = (
                inner_points[index]
            )

            points.append(
                upper_chine_outer_body_point(
                    inner_point,
                    side_sign
                )
            )

    for bow_index in range(
        len(bow_progress_values)
    ):
        bow_progress = (
            bow_progress_values[
                bow_index
            ]
        )

        inner_point = inner_points[
            body_station_count +
            bow_index
        ]

        if bow_progress <= UpperChineGapTaperStart:
            gap_factor = 1.0
        else:
            denominator = (
                1.0 -
                UpperChineGapTaperStart
            )

            local_parameter = (
                bow_progress -
                UpperChineGapTaperStart
            ) / denominator

            gap_factor = (
                1.0 -
                smootherstep(
                    local_parameter
                )
            )

        points.append(
            rg.Point3d(
                inner_point.X,
                inner_point.Y +
                side_sign *
                UpperChineOuterSideGap *
                gap_factor,
                inner_point.Z +
                UpperChineOuterHeightGap *
                gap_factor
            )
        )

    points.append(
        inner_points[-1]
    )

    return points

def create_extra_rail_points(
    side_sign,
    fraction,
    outer_body_points,
    sheer_body_points,
    stem_curve,
    bow_progress_values
):
    body_points = []

    for index in range(
        len(outer_body_points)
    ):
        body_points.append(
            lerp_point(
                outer_body_points[index],
                sheer_body_points[index],
                fraction
            )
        )

    outer_join_z = (
        H *
        UpperChineStemJoinHeightRatio
    )

    sheer_join_z = (
        H *
        SheerStemJoinHeightRatio
    )

    join_z = lerp(
        outer_join_z,
        sheer_join_z,
        fraction
    )

    stem_join_point = point_on_curve_at_z(
        stem_curve,
        join_z
    )

    return create_bow_bezier_points(
        body_points,
        stem_join_point,
        bow_progress_values,
        lerp(
            0.68,
            0.95,
            fraction
        )
    )

def create_section_curve(
    point_lower,
    point_upper,
    side_sign,
    panel_kind,
    section_kind,
    bow_progress
):
    if (
        point_lower.DistanceTo(
            point_upper
        ) <=
        sc.doc.ModelAbsoluteTolerance
    ):
        return None

    if panel_kind in [
        "bottom",
        "upper_band",
        "stem_front"
    ]:
        return rg.LineCurve(
            point_lower,
            point_upper
        )

    if section_kind == "stem":
        return rg.LineCurve(
            point_lower,
            point_upper
        )

    if panel_kind == "lower_side":
        body_bulge = (
            LowerSideBodyBulgeRatio
        )

        bow_bulge = (
            LowerSideBowBulgeRatio
        )
    else:
        body_bulge = (
            UpperSideBodyBulgeRatio
        )

        bow_bulge = (
            UpperSideBowBulgeRatio
        )

    if section_kind == "bow":
        middle_emphasis = math.sin(
            math.pi *
            bow_progress
        )

        stem_fade = (
            1.0 -
            smootherstep(
                bow_progress
            )
        )

        bulge_ratio = lerp(
            body_bulge,
            bow_bulge,
            middle_emphasis
        )

        bulge_ratio *= (
            0.35 +
            0.65 *
            stem_fade
        )
    else:
        bulge_ratio = (
            body_bulge
        )

    vector = (
        point_upper -
        point_lower
    )

    span_value = max(
        abs(vector.Y),
        abs(vector.Z) * 0.35
    )

    control_point_1 = lerp_point(
        point_lower,
        point_upper,
        1.0 / 3.0
    )

    control_point_2 = lerp_point(
        point_lower,
        point_upper,
        2.0 / 3.0
    )

    control_point_1.Y += (
        side_sign *
        span_value *
        bulge_ratio
    )

    control_point_2.Y += (
        side_sign *
        span_value *
        bulge_ratio
    )

    return rg.Curve.CreateControlPointCurve(
        [
            point_lower,
            control_point_1,
            control_point_2,
            point_upper
        ],
        3
    )

# MODULE 9: TẠO CÁC BỀ MẶT VỎ TÀU
# Nhiệm vụ: loft các dải bottom/side, tạo transom, ghép Brep và kiểm tra
# kết quả bề mặt theo topology của Model 112.

def create_panel_loft(
    section_curves,
    panel_name,
    collapse_end_point
):
    valid_curves = []

    for curve in section_curves:
        if curve is not None:
            valid_curves.append(
                curve
            )

    if len(valid_curves) < 2:
        print(
            "Not enough sections: %s" %
            panel_name
        )

        return None

    if collapse_end_point is None:
        end_point = (
            rg.Point3d.Unset
        )
    else:
        end_point = (
            collapse_end_point
        )

    try:
        breps = rg.Brep.CreateFromLoft(
            valid_curves,
            rg.Point3d.Unset,
            end_point,
            LoftType,
            False
        )

        if breps and len(breps) > 0:
            return breps[0]

    except Exception as loft_error:
        print(
            "Loft exception: %s, %s" %
            (
                panel_name,
                str(loft_error)
            )
        )

    try:
        breps = rg.Brep.CreateFromLoft(
            valid_curves,
            rg.Point3d.Unset,
            end_point,
            rg.LoftType.Loose,
            False
        )

        if breps and len(breps) > 0:
            print(
                "Loose loft fallback: %s" %
                panel_name
            )

            return breps[0]

    except Exception as loose_error:
        print(
            "Loose loft exception: %s, %s" %
            (
                panel_name,
                str(loose_error)
            )
        )

    print(
        "Loft failed: %s" %
        panel_name
    )

    return None


def orient_curve_start_near_point(curve, reference_point):
    """
    Sao chép curve và bảo đảm đầu curve nằm gần reference_point.

    Sweep2 nhạy với hướng rail. Hai rail phải cùng chạy từ đuôi -> mũi.
    Hàm này không sửa curve gốc trong layer khung.
    """
    if curve is None:
        return None

    duplicate = curve.DuplicateCurve()

    if duplicate is None:
        return None

    try:
        distance_start = duplicate.PointAtStart.DistanceTo(
            reference_point
        )
        distance_end = duplicate.PointAtEnd.DistanceTo(
            reference_point
        )

        if distance_end < distance_start:
            duplicate.Reverse()
    except Exception:
        pass

    return duplicate


def create_panel_two_longitudinal_rails(
    lower_rail,
    upper_rail,
    section_curves,
    panel_name
):
    """
    DỰNG MẶT THEO HAI ĐƯỜNG KHUNG DỌC.

    lower_rail và upper_rail là các đường longitudinal thật:
        keel / lower chine / upper chine / sheer.

    section_curves là các mặt cắt sườn ngang.

    Khác CreateFromLoft(section_curves):
    - Loft cũ chỉ lấy các sườn ngang làm điều kiện nội suy.
      Mép dọc của hai mặt kề nhau được Rhino tự sinh độc lập -> dễ hở.
    - Sweep2 mới bắt buộc hai mép dọc của mặt phải đi theo đúng rail.
      Hai panel kề nhau dùng CHUNG một rail -> mép hình học thống nhất.

    Nếu Sweep2 không tạo được mặt, chương trình mới fallback về Loft cũ.
    """
    if lower_rail is None or upper_rail is None:
        return None

    valid_sections = [
        curve for curve in section_curves
        if curve is not None
    ]

    if len(valid_sections) < 2:
        print(
            "Rail surface: not enough sections: %s" %
            panel_name
        )
        return None

    # Hai rail phải cùng hướng từ station đầu tiên về phía mũi.
    reference_lower = valid_sections[0].PointAtStart
    reference_upper = valid_sections[0].PointAtEnd

    rail_1 = orient_curve_start_near_point(
        lower_rail,
        reference_lower
    )

    rail_2 = orient_curve_start_near_point(
        upper_rail,
        reference_upper
    )

    if rail_1 is None or rail_2 is None:
        return None

    # Đảm bảo từng section chạy từ rail thấp -> rail cao.
    oriented_sections = []

    for section in valid_sections:
        section_copy = section.DuplicateCurve()

        try:
            start_point = section_copy.PointAtStart
            end_point = section_copy.PointAtEnd

            success_1s, _ = rail_1.ClosestPoint(start_point)
            success_2s, _ = rail_2.ClosestPoint(start_point)
            success_1e, _ = rail_1.ClosestPoint(end_point)
            success_2e, _ = rail_2.ClosestPoint(end_point)

            # So khoảng cách endpoint với hai rail bằng ClosestPoint + PointAt.
            if success_1s and success_2s and success_1e and success_2e:
                ok1s, t1s = rail_1.ClosestPoint(start_point)
                ok2s, t2s = rail_2.ClosestPoint(start_point)
                ok1e, t1e = rail_1.ClosestPoint(end_point)
                ok2e, t2e = rail_2.ClosestPoint(end_point)

                if ok1s and ok2s and ok1e and ok2e:
                    d_normal = (
                        start_point.DistanceTo(rail_1.PointAt(t1s)) +
                        end_point.DistanceTo(rail_2.PointAt(t2e))
                    )
                    d_reverse = (
                        start_point.DistanceTo(rail_2.PointAt(t2s)) +
                        end_point.DistanceTo(rail_1.PointAt(t1e))
                    )

                    if d_reverse < d_normal:
                        section_copy.Reverse()
        except Exception:
            pass

        oriented_sections.append(
            section_copy
        )

    tolerance = max(
        float(sc.doc.ModelAbsoluteTolerance) *
        float(JoinToleranceFactor),
        1.0e-6
    )

    # ------------------------------------------------------------------
    # ƯU TIÊN 1: Brep.CreateFromSweep - Sweep2 tổng quát của RhinoCommon.
    # ------------------------------------------------------------------
    try:
        sweep_breps = rg.Brep.CreateFromSweep(
            rail_1,
            rail_2,
            oriented_sections,
            False,
            tolerance
        )

        if sweep_breps and len(sweep_breps) > 0:
            if len(sweep_breps) == 1:
                result = sweep_breps[0]
            else:
                joined = rg.Brep.JoinBreps(
                    sweep_breps,
                    tolerance
                )

                if joined and len(joined) > 0:
                    result = joined[0]
                else:
                    result = sweep_breps[0]

            if result is not None and result.IsValid:
                print(
                    "Rail Sweep2 SUCCESS: %s" %
                    panel_name
                )
                return result
    except Exception as error:
        print(
            "Rail Sweep2 exception: %s | %s" %
            (
                panel_name,
                str(error)
            )
        )

    # ------------------------------------------------------------------
    # ƯU TIÊN 2: SweepTwoRail class - fallback riêng của RhinoCommon.
    # ------------------------------------------------------------------
    try:
        sweeper = rg.SweepTwoRail()
        sweeper.SweepTolerance = tolerance
        sweeper.AngleToleranceRadians = (
            sc.doc.ModelAngleToleranceRadians
        )
        sweeper.ClosedSweep = False

        sweep_breps = sweeper.PerformSweep(
            rail_1,
            rail_2,
            oriented_sections
        )

        if sweep_breps and len(sweep_breps) > 0:
            result = sweep_breps[0]

            if result is not None and result.IsValid:
                print(
                    "SweepTwoRail fallback SUCCESS: %s" %
                    panel_name
                )
                return result
    except Exception as error:
        print(
            "SweepTwoRail fallback exception: %s | %s" %
            (
                panel_name,
                str(error)
            )
        )

    # ------------------------------------------------------------------
    # FALLBACK CUỐI: Loft cũ.
    # Không làm chương trình mất khả năng dựng nếu một panel đặc biệt
    # ở mũi không phù hợp với Sweep2.
    # ------------------------------------------------------------------
    print(
        "Rail surface failed -> old Loft fallback: %s" %
        panel_name
    )

    return create_panel_loft(
        oriented_sections,
        panel_name + " [fallback loft]",
        None
    )



def closest_endpoint_assignment_to_two_rails(
    section_curve,
    rail_1,
    rail_2
):
    """
    Xác định endpoint nào của section nằm trên rail_1 / rail_2.

    Trả:
        point_on_rail_1,
        point_on_rail_2
    """
    if (
        section_curve is None or
        rail_1 is None or
        rail_2 is None
    ):
        return None, None

    point_a = section_curve.PointAtStart
    point_b = section_curve.PointAtEnd

    try:
        ok_1a, t_1a = rail_1.ClosestPoint(point_a)
        ok_2a, t_2a = rail_2.ClosestPoint(point_a)
        ok_1b, t_1b = rail_1.ClosestPoint(point_b)
        ok_2b, t_2b = rail_2.ClosestPoint(point_b)

        if (
            ok_1a and ok_2a and
            ok_1b and ok_2b
        ):
            normal_distance = (
                point_a.DistanceTo(
                    rail_1.PointAt(t_1a)
                ) +
                point_b.DistanceTo(
                    rail_2.PointAt(t_2b)
                )
            )

            reverse_distance = (
                point_a.DistanceTo(
                    rail_2.PointAt(t_2a)
                ) +
                point_b.DistanceTo(
                    rail_1.PointAt(t_1b)
                )
            )

            if reverse_distance < normal_distance:
                return point_b, point_a

    except Exception:
        pass

    return point_a, point_b


def create_bottom_forefoot_closure_patch(
    side_name,
    keel_rail,
    lower_chine_rail,
    last_bottom_section,
    lower_join_point
):
    """
    ĐÓNG PHẦN ĐÁY MŨI BỊ THIẾU.

    Sweep2 của bottom không nhận section suy biến tại lower_join_point,
    vì tại đây keel và lower-chine gặp nhau thành một điểm. Rhino vì thế
    thường dừng mặt ở section cuối cùng trước mũi.

    Mặt closure này dùng:
        edge 1 = đoạn keel_exact từ section cuối -> lower_join
        edge 2 = đoạn lower_chine từ section cuối -> lower_join

    Hai edge này là các đoạn TRIM từ đúng rail đang dùng cho Bottom /
    Lower Side, nên không tạo lại lỗi naked edge Lower Chine của V7.14.
    """
    if (
        keel_rail is None or
        lower_chine_rail is None or
        last_bottom_section is None or
        lower_join_point is None
    ):
        return None

    (
        keel_start_point,
        chine_start_point
    ) = closest_endpoint_assignment_to_two_rails(
        last_bottom_section,
        keel_rail,
        lower_chine_rail
    )

    if (
        keel_start_point is None or
        chine_start_point is None
    ):
        return None

    try:
        keel_tip_curve = trim_curve_between_points(
            keel_rail,
            keel_start_point,
            lower_join_point,
            side_name + " forefoot keel exact"
        )

        chine_tip_curve = trim_curve_between_points(
            lower_chine_rail,
            chine_start_point,
            lower_join_point,
            side_name + " forefoot lower chine exact"
        )
    except Exception as error:
        print(
            "forefoot trim failed %s: %s" %
            (
                side_name,
                str(error)
            )
        )
        return None

    # Hai curve cần cùng hướng:
    # section cuối -> lower_join.
    keel_tip_curve = orient_curve_start_near_point(
        keel_tip_curve,
        keel_start_point
    )

    chine_tip_curve = orient_curve_start_near_point(
        chine_tip_curve,
        chine_start_point
    )

    # ------------------------------------------------------------------
    # ƯU TIÊN 1:
    # Ruled surface. Bottom section vốn là đường thẳng nên ruled patch
    # là cách tự nhiên để nối hai rail hội tụ về cùng một điểm.
    # ------------------------------------------------------------------
    patch = create_ruled_surface(
        keel_tip_curve,
        chine_tip_curve,
        side_name + " bottom forefoot closure"
    )

    if (
        patch is not None and
        patch.IsValid
    ):
        print(
            "forefoot closure SUCCESS (ruled): %s" %
            side_name
        )
        return patch

    # ------------------------------------------------------------------
    # ƯU TIÊN 2:
    # EdgeSrf fallback với đúng 3 biên hình học.
    # ------------------------------------------------------------------
    try:
        boundary_curves = [
            keel_tip_curve,
            chine_tip_curve,
            last_bottom_section.DuplicateCurve()
        ]

        patch = rg.Brep.CreateEdgeSurface(
            boundary_curves
        )

        if (
            patch is not None and
            patch.IsValid
        ):
            print(
                "forefoot closure SUCCESS (EdgeSrf): %s" %
                side_name
            )
            return patch

    except Exception as error:
        print(
            "EdgeSrf fallback failed %s: %s" %
            (
                side_name,
                str(error)
            )
        )

    print(
        "forefoot closure FAILED: %s" %
        side_name
    )

    return None



def create_planar_panel(
    points,
    panel_name
):
    # Bk = 0 làm hai đỉnh keel của panel transom trùng nhau. Một tam giác
    # hợp lệ không được chuyển thành PolylineCurve có cạnh dài bằng 0.
    point_tolerance = max(float(sc.doc.ModelAbsoluteTolerance), 1.0e-9)
    polygon_points = []
    for point in points:
        if (not polygon_points or
                point.DistanceTo(polygon_points[-1]) > point_tolerance):
            polygon_points.append(point)

    if (len(polygon_points) > 1 and
            polygon_points[0].DistanceTo(polygon_points[-1]) <= point_tolerance):
        polygon_points.pop()

    if len(polygon_points) < 3:
        print("Planar surface degenerate: %s" % panel_name)
        return None

    polygon_points.append(polygon_points[0])

    loop_curve = rg.PolylineCurve(
        polygon_points
    )

    breps = rg.Brep.CreatePlanarBreps(
        loop_curve,
        sc.doc.ModelAbsoluteTolerance *
        JoinToleranceFactor
    )

    if breps and len(breps) > 0:
        return breps[0]

    print(
        "Planar surface failed: %s" %
        panel_name
    )

    return None

def create_ruled_surface(
    curve_a,
    curve_b,
    surface_name
):
    try:
        surface = (
            rg.NurbsSurface.CreateRuledSurface(
                curve_a,
                curve_b
            )
        )

        if (
            surface is not None and
            surface.IsValid
        ):
            return surface.ToBrep()

    except Exception as ruled_error:
        print(
            "Ruled surface exception: %s, %s" %
            (
                surface_name,
                str(ruled_error)
            )
        )

    return None

def trim_curve_between_points(
    curve,
    start_point,
    end_point,
    curve_name
):
    success_start, start_parameter = curve.ClosestPoint(
        start_point
    )

    success_end, end_parameter = curve.ClosestPoint(
        end_point
    )

    if not success_start or not success_end:
        raise Exception(
            "Could not trim curve: " +
            curve_name
        )

    if end_parameter < start_parameter:
        temporary = start_parameter
        start_parameter = end_parameter
        end_parameter = temporary

    trimmed_curve = curve.Trim(
        start_parameter,
        end_parameter
    )

    if trimmed_curve is None:
        raise Exception(
            "Trim failed: " +
            curve_name
        )

    return trimmed_curve

def create_split_side_panels(
    side_name,
    side_sign,
    panel_kind,
    lower_points,
    upper_points,
    section_kinds,
    bow_progress_by_section
):
    split_index = (
        int(BodyStationCount) -
        1
    )

    split_section = create_section_curve(
        lower_points[split_index],
        upper_points[split_index],
        side_sign,
        panel_kind,
        section_kinds[split_index],
        bow_progress_by_section[
            split_index
        ]
    )

    body_sections = []

    for section_index in range(
        split_index + 1
    ):
        section_curve = create_section_curve(
            lower_points[
                section_index
            ],
            upper_points[
                section_index
            ],
            side_sign,
            panel_kind,
            section_kinds[
                section_index
            ],
            bow_progress_by_section[
                section_index
            ]
        )

        if section_curve is not None:
            body_sections.append(
                section_curve
            )

    bow_sections = [
        split_section.DuplicateCurve()
    ]

    end_distance = (
        lower_points[-1].DistanceTo(
            upper_points[-1]
        )
    )

    collapse_end_point = None

    if (
        end_distance <=
        sc.doc.ModelAbsoluteTolerance *
        JoinToleranceFactor
    ):
        collapse_end_point = (
            lower_points[-1]
        )

        final_section_index = (
            len(section_kinds) -
            1
        )
    else:
        final_section_index = (
            len(section_kinds)
        )

    for section_index in range(
        split_index + 1,
        final_section_index
    ):
        section_curve = create_section_curve(
            lower_points[
                section_index
            ],
            upper_points[
                section_index
            ],
            side_sign,
            panel_kind,
            section_kinds[
                section_index
            ],
            bow_progress_by_section[
                section_index
            ]
        )

        if section_curve is not None:
            bow_sections.append(
                section_curve
            )

    body_panel = create_panel_loft(
        body_sections,
        (
            side_name +
            " " +
            panel_kind +
            " body"
        ),
        None
    )

    bow_panel = create_panel_loft(
        bow_sections,
        (
            side_name +
            " " +
            panel_kind +
            " bow"
        ),
        collapse_end_point
    )

    return (
        body_panel,
        bow_panel,
        split_section
    )

def create_split_bottom_panels(
    side_name,
    side_sign,
    keel_points,
    lower_points,
    lower_rail,
    keel_body_curve,
    stem_curve,
    lower_join_point,
    section_kinds,
    bow_progress_by_section
):
    split_point_keel = keel_body_curve.PointAtEnd
    split_x = split_point_keel.X
    split_point_lower = point_on_curve_at_x(
        lower_rail,
        split_x
    )

    split_section = rg.LineCurve(
        split_point_keel,
        split_point_lower
    )

    body_sections = []
    stem_sections = []

    for section_index in range(
        len(section_kinds) - 1
    ):
        keel_point = keel_points[
            section_index
        ]

        lower_point = lower_points[
            section_index
        ]

        section_curve = create_section_curve(
            keel_point,
            lower_point,
            side_sign,
            "bottom",
            section_kinds[
                section_index
            ],
            bow_progress_by_section[
                section_index
            ]
        )

        section_x = max(
            keel_point.X,
            lower_point.X
        )

        if (
            section_x <
            split_x -
            sc.doc.ModelAbsoluteTolerance
        ):
            body_sections.append(
                section_curve
            )
        elif (
            section_x >
            split_x +
            sc.doc.ModelAbsoluteTolerance
        ):
            stem_sections.append(
                section_curve
            )

    body_sections.append(
        split_section
    )

    stem_sections.insert(
        0,
        split_section.DuplicateCurve()
    )

    if len(stem_sections) < 3:
        stem_sections = [
            split_section.DuplicateCurve()
        ]

        for local_parameter in [
            0.40,
            0.72
        ]:
            target_x = lerp(
                split_x,
                lower_join_point.X,
                local_parameter
            )

            keel_point = point_on_curve_at_x(
                stem_curve,
                target_x
            )

            lower_point = point_on_curve_at_x(
                lower_rail,
                target_x
            )

            stem_sections.append(
                rg.LineCurve(
                    keel_point,
                    lower_point
                )
            )

    body_panel = create_panel_loft(
        body_sections,
        side_name +
        " bottom body",
        None
    )

    stem_panel = create_panel_loft(
        stem_sections,
        side_name +
        " bottom forefoot",
        lower_join_point
    )

    return (
        body_panel,
        stem_panel,
        split_section
    )

def create_section_metadata(
    body_station_count,
    bow_progress_values
):
    section_kinds = []
    bow_progress_by_section = []

    for index in range(
        body_station_count
    ):
        section_kinds.append(
            "body"
        )

        bow_progress_by_section.append(
            0.0
        )

    for bow_progress in bow_progress_values:
        section_kinds.append(
            "bow"
        )

        bow_progress_by_section.append(
            bow_progress
        )

    section_kinds.append(
        "stem"
    )

    bow_progress_by_section.append(
        1.0
    )

    return (
        section_kinds,
        bow_progress_by_section
    )

def validate_monotonic_bow(
    points,
    rail_name,
    side_sign,
    body_station_count
):
    start_index = (
        body_station_count -
        1
    )

    for index in range(
        start_index,
        len(points) - 1
    ):
        current_point = points[index]
        next_point = points[index + 1]

        if (
            next_point.X <
            current_point.X -
            sc.doc.ModelAbsoluteTolerance
        ):
            raise Exception(
                "Bow X reversal in rail: " +
                rail_name
            )

        if (
            abs(next_point.Y) >
            abs(current_point.Y) +
            sc.doc.ModelAbsoluteTolerance
        ):
            raise Exception(
                "Bow beam reversal in rail: " +
                rail_name
            )

def validate_upper_chine_gap(
    inner_points,
    outer_points,
    body_station_count
):
    tolerance = max(
        sc.doc.ModelAbsoluteTolerance *
        10.0,
        0.5
    )

    for index in range(
        body_station_count
    ):
        height_gap = (
            outer_points[index].Z -
            inner_points[index].Z
        )

        if abs(
            height_gap -
            UpperChineOuterHeightGap
        ) > tolerance:
            raise Exception(
                "Upper chine vertical gap is invalid."
            )

def show_station_geometry(
    port_level_points,
    starboard_level_points,
    section_kinds,
    bow_progress_by_section,
    panel_kinds
):
    section_count = len(
        section_kinds
    )

    for section_index in range(
        section_count
    ):
        section_kind = (
            section_kinds[
                section_index
            ]
        )

        should_show = False

        if (
            section_kind == "body" and
            ShowBodyStations
        ):
            should_show = True

        if (
            section_kind == "bow" and
            ShowBowFairingSections
        ):
            should_show = True

        if not should_show:
            continue

        station_port_keel = (
            port_level_points[0][
                section_index
            ]
        )
        station_starboard_keel = (
            starboard_level_points[0][
                section_index
            ]
        )

        station_start = (
            midpoint_on_centerplane(
                station_port_keel,
                station_starboard_keel
            )
            if CreateHalfModel
            else station_port_keel
        )

        # Bk=0: hai điểm keel trùng nhau, không tạo đoạn ngang độ dài 0.
        # Đường keel dọc thân được thêm trong hull_line_records bên dưới.
        if station_start.DistanceTo(station_starboard_keel) > max(
            sc.doc.ModelAbsoluteTolerance, 1.0e-9
        ):
            add_curve(
                rg.LineCurve(station_start, station_starboard_keel)
            )

        for level_index in range(
            len(panel_kinds)
        ):
            port_curve = create_section_curve(
                port_level_points[
                    level_index
                ][section_index],
                port_level_points[
                    level_index + 1
                ][section_index],
                -1.0,
                panel_kinds[level_index],
                section_kind,
                bow_progress_by_section[
                    section_index
                ]
            )

            starboard_curve = create_section_curve(
                starboard_level_points[
                    level_index
                ][section_index],
                starboard_level_points[
                    level_index + 1
                ][section_index],
                1.0,
                panel_kinds[level_index],
                section_kind,
                bow_progress_by_section[
                    section_index
                ]
            )

            if not CreateHalfModel:
                add_curve(
                    port_curve
                )

            add_curve(
                starboard_curve
            )

def add_design_points(
    point_groups
):
    if not ShowDesignPoints:
        return

    for points in point_groups:
        for point in points:
            add_point(
                point
            )


# MODULE 10: TỔ CHỨC DỮ LIỆU VÀ XUẤT KẾT QUẢ
# Nhiệm vụ: lập bảng tham số, bảng station và xuất CSV khi Chế độ 1 yêu cầu.
# Khi khảo sát hàng loạt, phần xuất CSV được tắt để tránh ghi đè nhiều file.

def build_station_records(
    section_kinds,
    starboard_level_points
):
    records = []

    level_count = len(starboard_level_points)

    if level_count < 3:
        raise Exception(
            "At least Keel, Lower Chine and Sheer are required."
        )

    keel_points = starboard_level_points[0]
    lower_points = starboard_level_points[1]
    sheer_points = starboard_level_points[-1]

    upper_inner_points = (
        starboard_level_points[2]
        if level_count >= 4
        else None
    )

    upper_outer_points = (
        starboard_level_points[3]
        if level_count >= 5
        else None
    )

    for index in range(len(section_kinds)):
        records.append(
            StationRecord(
                "S%02d" % index,
                section_kinds[index],
                keel_points[index],
                lower_points[index],
                (
                    upper_inner_points[index]
                    if upper_inner_points is not None
                    else None
                ),
                (
                    upper_outer_points[index]
                    if upper_outer_points is not None
                    else None
                ),
                sheer_points[index],
                L
            )
        )

    return records


def build_export_run_token():
    """Tên phiên xuất đủ chi tiết để hai lần bấm liên tiếp không trùng file."""
    now_value = datetime.datetime.now()

    return (
        "%s_%03d" % (
            now_value.strftime(
                "%Y%m%d_%H%M%S"
            ),
            int(
                now_value.microsecond / 1000
            )
        )
    )


def ensure_writable_directory(
    directory_path
):
    """Tạo thư mục và thử ghi file nhỏ; trả True nếu dùng được."""
    if not directory_path:
        return False

    try:
        System.IO.Directory.CreateDirectory(
            directory_path
        )

        test_name = (
            ".model112_write_test_%s.tmp" %
            System.Guid.NewGuid().ToString(
                "N"
            )
        )

        test_path = os.path.join(
            directory_path,
            test_name
        )

        with io.open(
            test_path,
            "w",
            encoding="utf-8"
        ) as test_file:
            test_file.write(
                u"MODEL112"
            )

        try:
            os.remove(
                test_path
            )
        except Exception:
            pass

        return True

    except Exception:
        return False


def get_model112_appdata_directory():
    """Thư mục dữ liệu ứng dụng không phụ thuộc tên user/ổ đĩa cụ thể."""
    appdata = None

    try:
        appdata = (
            System.Environment.GetFolderPath(
                System.Environment.SpecialFolder.ApplicationData
            )
        )
    except Exception:
        appdata = None

    if not appdata:
        appdata = os.environ.get(
            "APPDATA",
            os.path.expanduser(
                "~"
            )
        )

    return os.path.join(
        appdata,
        "Model112"
    )


def write_model112_data_manifest(
    output_directory
):
    """
    Model112_Data là OUTPUT-ONLY.

    V19 không đọc parameters/station/hydro CSV cũ để dựng tàu. Vì vậy một thư
    mục Model112_Data có sẵn trên máy không phải điều kiện để chương trình chạy.
    File manifest chỉ ghi thông tin phiên bản, không được dùng làm đầu vào.
    """
    manifest_path = os.path.join(
        output_directory,
        "MODEL112_DATA_INFO.txt"
    )

    content = (
        u"MODEL 112 DATA FOLDER\n"
        u"code_version=%s\n"
        u"data_schema=%d\n"
        u"mode=OUTPUT_ONLY\n"
        u"note=Existing CSV files are not loaded as geometry input.\n"
    ) % (
        MODEL112_CODE_VERSION,
        int(
            MODEL112_DATA_SCHEMA_VERSION
        )
    )

    try:
        with io.open(
            manifest_path,
            "w",
            encoding="utf-8-sig"
        ) as output_file:
            output_file.write(
                content
            )
    except Exception:
        # Manifest không phải dữ liệu bắt buộc; lỗi ghi manifest không làm
        # dừng quá trình tạo vỏ.
        pass


def get_data_output_directory():
    """
    Chọn thư mục xuất theo thứ tự an toàn:
    1) cạnh file .3dm nếu document đã Save và thư mục có quyền ghi;
    2) %%APPDATA%%\\Model112\\Data;
    3) Desktop\\Model112_Data.

    Không dùng đường dẫn cứng theo ổ C:/D:/I: hoặc tên tài khoản của tác giả.
    """
    candidates = []

    document_path = sc.doc.Path

    if document_path:
        candidates.append(
            os.path.join(
                os.path.dirname(
                    document_path
                ),
                DataOutputFolderName
            )
        )

    candidates.append(
        os.path.join(
            get_model112_appdata_directory(),
            "Data"
        )
    )

    try:
        desktop_directory = (
            System.Environment.GetFolderPath(
                System.Environment.SpecialFolder.Desktop
            )
        )
    except Exception:
        desktop_directory = None

    if desktop_directory:
        candidates.append(
            os.path.join(
                desktop_directory,
                DataOutputFolderName
            )
        )

    checked = []

    for candidate in candidates:
        if not candidate:
            continue

        normalized = os.path.normpath(
            candidate
        )

        if normalized in checked:
            continue

        checked.append(
            normalized
        )

        if ensure_writable_directory(
            normalized
        ):
            write_model112_data_manifest(
                normalized
            )

            return normalized

    raise Exception(
        u"MODEL 112 không tìm được thư mục có quyền ghi dữ liệu. "
        u"Hãy kiểm tra quyền ghi thư mục chứa file Rhino hoặc thư mục AppData."
    )


def get_excel_csv_settings():
    """
    MODEL 112 V19 dùng định dạng CSV thống nhất, không phụ thuộc locale Windows:

        - Dấu phân cách cột: dấu phẩy ","
        - Dấu thập phân: dấu chấm "."

    Ví dụ:
        "1","7.000000","35.000000","2.500000"

    Cách này tránh tình trạng Excel tách số thập phân thành nhiều cột khi
    Windows/Excel trên máy người dùng đang nhận dấu phẩy là dấu phân cột.
    """
    return (
        ",",
        "."
    )


def csv_text(
    value,
    decimal_separator="."
):
    if isinstance(
        value,
        float
    ):
        text_value = (
            "%.6f" %
            value
        )

        if decimal_separator != ".":
            text_value = text_value.replace(
                ".",
                decimal_separator
            )

        return text_value

    try:
        return TEXT_TYPE(
            value
        )
    except Exception:
        return str(
            value
        )


def write_csv_file(
    file_path,
    rows
):
    """
    MODEL 112 V20 - CSV chuẩn hóa:

    - delimiter = ','
    - decimal = '.'
    - UTF-8 BOM chỉ ghi đúng MỘT LẦN ở đầu file
    - CRLF để tương thích tốt với Excel/Windows

    Không dùng io.open(..., encoding='utf-8-sig') theo từng lần write để tránh
    trường hợp IronPython ghi lại BOM ở đầu nhiều dòng trên một số môi trường.
    """
    import codecs

    delimiter, decimal_separator = (
        get_excel_csv_settings()
    )

    output_lines = []

    for row in rows:
        values = []

        for value in row:
            text_value = csv_text(
                value,
                decimal_separator
            )

            text_value = text_value.replace(
                '"',
                '""'
            )

            values.append(
                u'"' +
                TEXT_TYPE(
                    text_value
                ) +
                u'"'
            )

        output_lines.append(
            delimiter.join(
                values
            )
        )

    content = (
        u"\r\n".join(
            output_lines
        ) +
        u"\r\n"
    )

    with open(
        file_path,
        "wb"
    ) as output_file:
        output_file.write(
            codecs.BOM_UTF8
        )

        output_file.write(
            content.encode(
                "utf-8"
            )
        )


def write_csv_file_safe(
    desired_path,
    rows,
    avoid_overwrite=True
):
    """
    Không ghi đè file cũ. Nếu file đang mở trong Excel hoặc không ghi được,
    thử tên _01/_02... trong cùng thư mục. Trả (path_thực_tế, đã_đổi_tên).
    """
    actual_path = desired_path
    renamed = False

    if (
        avoid_overwrite and
        os.path.exists(
            actual_path
        )
    ):
        actual_path = make_duplicate_safe_path(
            actual_path
        )
        renamed = True

    try:
        write_csv_file(
            actual_path,
            rows
        )

        return (
            actual_path,
            renamed
        )

    except (IOError, OSError):
        alternate_path = make_duplicate_safe_path(
            desired_path
        )

        write_csv_file(
            alternate_path,
            rows
        )

        return (
            alternate_path,
            True
        )


def export_parameter_catalog(
    run_token=None
):
    rows = [
        (
            "group",
            "symbol",
            "code_name",
            "unit",
            "value",
            "role"
        )
    ]

    rows.extend(
        PARAMETER_CATALOG
    )

    if not run_token:
        run_token = build_export_run_token()

    output_path = os.path.join(
        get_data_output_directory(),
        (
            "Model112_parameters_%s.csv" %
            run_token
        )
    )

    actual_path, renamed = write_csv_file_safe(
        output_path,
        rows,
        True
    )

    print(
        "Parameter table: %s" %
        actual_path
    )

    return actual_path


def station_record_active_features(records):
    feature_specs = [
        ("keel", "keel_point"),
        ("lower", "lower_point"),
        ("upper_inner", "upper_inner_point"),
        ("upper_outer", "upper_outer_point"),
        ("sheer", "sheer_point")
    ]

    active_specs = []

    for label, attr_name in feature_specs:
        if any(
            getattr(record, attr_name, None) is not None
            for record in records
        ):
            active_specs.append(
                (label, attr_name)
            )

    return active_specs


def station_point_export_values(point):
    if point is None:
        return ("", "", "")

    return (
        model_units_to_meters(
            point.X,
            GeometryUnitsPerMeter
        ),
        model_units_to_meters(
            point.Y,
            GeometryUnitsPerMeter
        ),
        model_units_to_meters(
            point.Z,
            GeometryUnitsPerMeter
        )
    )


def export_station_records(
    records,
    run_token=None
):
    active_specs = station_record_active_features(
        records
    )

    header = [
        "station_id",
        "section_kind",
        "reference_x_ratio"
    ]

    for label, attr_name in active_specs:
        header.extend(
            [
                label + "_x_m",
                label + "_y_m",
                label + "_z_m"
            ]
        )

    rows = [
        tuple(header)
    ]

    for record in records:
        row = [
            record.station_id,
            record.section_kind,
            record.reference_x_ratio
        ]

        for label, attr_name in active_specs:
            point = getattr(
                record,
                attr_name,
                None
            )

            row.extend(
                station_point_export_values(
                    point
                )
            )

        rows.append(
            tuple(row)
        )

    if not run_token:
        run_token = build_export_run_token()

    output_path = os.path.join(
        get_data_output_directory(),
        (
            "Model112_station_%s.csv" %
            run_token
        )
    )

    actual_path, renamed = write_csv_file_safe(
        output_path,
        rows,
        True
    )

    print(
        "Station table: %s" %
        actual_path
    )

    return actual_path


def print_parameter_method_summary():
    print(
        "PARAMETER METHOD:"
    )
    print(
        "HullParameters -> DerivedHullData -> Control Points -> Form Curves -> Stations -> Surface Panels -> Hull"
    )
    print(
        "Primary controls: beta_M=%.3f deg, beta_T=%.3f deg, Z_B=%.3f m" %
        (
            DeadriseMidshipAngle,
            DeadriseSternAngle,
            model_units_to_meters(
                LowerChineBowEndHeight,
                GeometryUnitsPerMeter
            )
        )
    )


# MODULE 11: GIỚI HẠN VÀ KIỂM TRA TÍNH HỢP LỆ CỦA THAM SỐ
# Nhiệm vụ: chặn các tổ hợp giá trị không hợp lý trước khi dựng hình, ví dụ
# T >= H, B >= L, góc vượt miền cho phép hoặc topology station không hợp lệ.

def validate_parameters():
    errors = []

    if L <= 0.0 or B <= 0.0 or H <= 0.0:
        errors.append(
            "L, B and H must be greater than zero."
        )

    if T <= 0.0 or T >= H:
        errors.append(
            "T must be greater than zero and smaller than H."
        )

    if B >= L:
        errors.append(
            "B must be smaller than L."
        )

    if KeelWidth < 0.0:
        errors.append(
            "KeelWidth must be greater than or equal to zero."
        )

    if (
        B > 0.0 and
        KeelWidth >= B * 0.20
    ):
        errors.append(
            "KeelWidth must be smaller than 20 percent of B."
        )

    if (
        BowRakeAngle < 5.0 or
        BowRakeAngle > 45.0
    ):
        errors.append(
            "BowRakeAngle must be between 5 and 45 degrees."
        )

    if (
        BowBodyStartRatio <=
        LowerChineFull2XRatio or
        BowBodyStartRatio >=
        stem_start_ratio()
    ):
        errors.append(
            "BowBodyStartRatio is invalid."
        )

    if (
        LowerChineBowEndHeight <=
        DERIVED.stem_start_z or
        LowerChineBowEndHeight >=
        H * UpperChineStemJoinHeightRatio
    ):
        errors.append(
            "LowerChineBowEndHeight must be above stem start and below upper chine join."
        )

    if (
        SheerBowShoulderXRatio <=
        LowerChineFull1XRatio or
        SheerBowShoulderXRatio >=
        BowBodyStartRatio
    ):
        errors.append(
            "SheerBowShoulderXRatio is invalid."
        )

    if (
        DeadriseMidshipXRatio <= 0.0 or
        DeadriseMidshipXRatio >=
        BowBodyStartRatio
    ):
        errors.append(
            "DeadriseMidshipXRatio is invalid."
        )

    if (
        TransomRakeAngle < 0.0 or
        TransomRakeAngle > 20.0
    ):
        errors.append(
            "TransomRakeAngle must be between 0 and 20 degrees."
        )

    if (
        TransomKeelForwardOffset < 0.0 or
        TransomKeelForwardOffset >=
        L * 0.10
    ):
        errors.append(
            "TransomKeelForwardOffset is invalid."
        )

    deadrise_angles = [
        DeadriseSternAngle,
        DeadriseMidshipAngle,
        DeadriseBowAngle
    ]

    for angle_value in deadrise_angles:
        if (
            angle_value < 0.0 or
            angle_value > 35.0
        ):
            errors.append(
                "All deadrise angles must be between 0 and 35 degrees."
            )

            break

    if (
        LowerChineMaxBeamRatio <= 0.0 or
        LowerChineMaxBeamRatio >= 1.0
    ):
        errors.append(
            "LowerChineMaxBeamRatio must be between 0 and 1."
        )

    if (
        UpperChineInnerMaxBeamRatio <=
        LowerChineMaxBeamRatio or
        UpperChineInnerMaxBeamRatio >=
        SheerMaxBeamRatio
    ):
        errors.append(
            "UpperChineInnerMaxBeamRatio is invalid."
        )

    if (
        UpperChineOuterHeightGap <= 0.0
    ):
        errors.append(
            "UpperChineOuterHeightGap must be greater than zero."
        )

    if (
        UpperChineOuterSideGap <= 0.0
    ):
        errors.append(
            "UpperChineOuterSideGap must be greater than zero."
        )

    if (
        UpperChineGapTaperStart < 0.0 or
        UpperChineGapTaperStart >= 1.0
    ):
        errors.append(
            "UpperChineGapTaperStart must be between 0 and 1."
        )

    if (
        int(TotalKnuckleCountPerSide) !=
        TotalKnuckleCountPerSide or
        TotalKnuckleCountPerSide < 1 or
        TotalKnuckleCountPerSide > 3
    ):
        errors.append(
            "TotalKnuckleCountPerSide must be an integer between 1 and 3."
        )

    if (
        int(BodyStationCount) !=
        BodyStationCount or
        BodyStationCount < 3 or
        BodyStationCount > 15
    ):
        errors.append(
            "BodyStationCount must be an integer between 3 and 15."
        )

    if (
        int(BowFairingSectionCount) !=
        BowFairingSectionCount or
        BowFairingSectionCount < 2 or
        BowFairingSectionCount > 5
    ):
        errors.append(
            "BowFairingSectionCount must be an integer between 2 and 5."
        )

    total_section_count = (
        int(BodyStationCount) +
        int(BowFairingSectionCount) +
        1
    )

    if (
        total_section_count >
        MaximumTotalSectionCount
    ):
        errors.append(
            "Total section count exceeds MaximumTotalSectionCount."
        )

    if (
        UpperChineStemJoinHeightRatio <=
        UpperChineInnerHeightRatio
    ):
        errors.append(
            "UpperChineStemJoinHeightRatio must be above UpperChineInnerHeightRatio."
        )

    if (
        SheerStemJoinHeightRatio <=
        UpperChineStemJoinHeightRatio or
        SheerStemJoinHeightRatio >
        StemTipHeightRatio
    ):
        errors.append(
            "SheerStemJoinHeightRatio is invalid."
        )

    if (
        SheerSagDepthRatio < 0.0 or
        SheerSagDepthRatio > 0.12
    ):
        errors.append(
            "SheerSagDepthRatio must be between 0 and 0.12 (inclusive)."
        )

    if (
        SheerSagShapePower < 0.50 or
        SheerSagShapePower > 4.00
    ):
        errors.append(
            "SheerSagShapePower must be between 0.50 and 4.00."
        )

    if (
        SheerSagPositionRatio <= 0.10 or
        SheerSagPositionRatio >= 0.90
    ):
        errors.append(
            "SheerSagPositionRatio must be between 0.10 and 0.90."
        )

    return errors


# =============================================================================
# V20: CHẨN ĐOÁN THAM SỐ / HÌNH HỌC TRƯỚC KHI DỰNG
# =============================================================================

def v20_add_diagnostic(items, status, category, region, message):
    items.append({
        "status": status,
        "category": category,
        "region": region,
        "message": message
    })


def v20_parameter_diagnostics(params):
    """Kiểm tra nhanh các ràng buộc phụ thuộc trước Preview/Create."""
    items = []
    units = float(getattr(params, "units_per_meter", 1.0) or 1.0)
    Lm = float(params.length) / units
    Bm = float(params.beam) / units
    Hm = float(params.depth) / units
    Tm = float(params.draft) / units
    Bk = float(getattr(params, "keel_width", 0.0)) / units
    zb = float(getattr(params, "lower_chine_bow_end_height", 0.0)) / units
    stem_start = Hm * float(getattr(params, "c_height_ratio", 0.04))
    upper_join = Hm * float(getattr(params, "upper_chine_stem_join_height_ratio", 0.72))
    body_ratio = float(getattr(params, "upper_chine_inner_height_ratio", 0.60))
    join_ratio = float(getattr(params, "upper_chine_stem_join_height_ratio", 0.72))
    nbody = int(round(float(getattr(params, "body_station_count", 0))))
    nbow = int(round(float(getattr(params, "bow_fairing_section_count", 0))))

    if min(Lm, Bm, Hm) <= 0.0:
        v20_add_diagnostic(items, "INVALID", u"THAM SỐ", u"KÍCH THƯỚC", u"L, B và H phải lớn hơn 0.")
    if Tm < 0.0 or (Hm > 0.0 and Tm >= Hm):
        v20_add_diagnostic(items, "INVALID", u"THAM SỐ", u"MỚN NƯỚC", u"T phải thỏa 0 ≤ T < H.")
    if Bk < 0.0 or (Bm > 0.0 and Bk >= 0.20 * Bm):
        v20_add_diagnostic(items, "INVALID", u"THAM SỐ", u"ĐÁY/KEEL", u"Bk phải nằm trong [0; 0,20B).")
    if nbody < 3 or nbody > 15:
        v20_add_diagnostic(items, "INVALID", u"PHƯƠNG PHÁP", u"THÂN", u"Số sườn dựng thân phải từ 3 đến 15.")
    elif nbody >= 13:
        v20_add_diagnostic(items, "WARNING", u"PHƯƠNG PHÁP", u"THÂN", u"Mật độ sườn dựng thân cao; nếu Sweep2 mất ổn định hãy giảm số sườn trước khi tăng tolerance.")
    if nbow < 2 or nbow > 5:
        v20_add_diagnostic(items, "INVALID", u"PHƯƠNG PHÁP", u"MŨI", u"Số mặt cắt làm trơn mũi phải từ 2 đến 5.")
    if Hm > 0.0 and not (stem_start < zb < upper_join):
        v20_add_diagnostic(items, "INVALID", u"HÌNH HỌC", u"MŨI", u"ZB = %.3f m phải nằm giữa cao độ bắt đầu sống mũi %.3f m và điểm nối chine trên %.3f m." % (zb, stem_start, upper_join))
    elif Hm > 0.0:
        clearance = min(zb-stem_start, upper_join-zb)
        if clearance < 0.03*Hm:
            v20_add_diagnostic(items, "WARNING", u"HÌNH HỌC", u"MŨI", u"ZB đang gần giới hạn hình học; khoảng hở nhỏ nhất %.3f m." % clearance)
    if join_ratio <= body_ratio:
        v20_add_diagnostic(items, "INVALID", u"HÌNH HỌC", u"CHINE TRÊN", u"Tỷ lệ cao điểm nối chine trên tại mũi phải lớn hơn tỷ lệ cao chine trên vùng thân.")
    elif join_ratio - body_ratio < 0.03:
        v20_add_diagnostic(items, "WARNING", u"HÌNH HỌC", u"CHINE TRÊN", u"Hai tỷ lệ cao của chine trên quá gần nhau; vùng chuyển tiếp mũi có thể kém ổn định.")
    if Bk > 0.0:
        v20_add_diagnostic(items, "WARNING", u"TOPOLOGY", u"KEEL/FOREFOOT", u"Bk > 0 tạo thêm keel strip và forefoot strip. Sau khi dựng nên kiểm tra naked edge và đường nước vùng mũi; không dùng tăng tolerance để che khe hở hình học.")

    status = "VALID"
    if any(x["status"] == "INVALID" for x in items):
        status = "INVALID"
    elif any(x["status"] == "WARNING" for x in items):
        status = "WARNING"
    return status, items


def v20_format_diagnostics(status, items, max_items=3):
    if not items:
        return u"[%s] Bộ tham số hiện tại đạt kiểm tra trước khi dựng." % status
    lines = []
    for item in items[:max_items]:
        lines.append(u"[%s][%s][%s] %s" % (
            item["status"], item["category"], item["region"], item["message"]
        ))
    if len(items) > max_items:
        lines.append(u"... còn %d cảnh báo/ghi chú." % (len(items)-max_items))
    return u" | ".join(lines)


# MODULE 12: BỘ ĐIỀU KHIỂN QUÁ TRÌNH DỰNG VỎ
# Nhiệm vụ: nhận một HullParameters hoàn chỉnh, đồng bộ dữ liệu, kiểm tra,
# gọi lần lượt các module hình học, quản lý Preview/Group và trả về object IDs.

PREVIEW_STICKY_KEY = "MODEL_112_V19_PREVIEW_IDS"
SURVEY_STICKY_KEY = "MODEL_112_V19_SURVEY_IDS"
FINAL_HULL_OBJECTS_STICKY_KEY = "MODEL_112_FINAL_HULL_OBJECT_IDS"
FINAL_HULL_IS_HALF_STICKY_KEY = "MODEL_112_FINAL_HULL_IS_HALF"
HIDDEN_LINESPLAN_SOURCE_STICKY_KEY = "MODEL_112_HIDDEN_SOURCE_FOR_HALF_IDS"
FINAL_HULL_LINES_STICKY_KEY = "MODEL_112_FINAL_HULL_LINES"
LINESPLAN_SOURCE_STICKY_KEY = "MODEL_112_LINESPLAN_SOURCE_IDS"
LINESPLAN_DATA_STICKY_KEY = "MODEL_112_LINESPLAN_SOURCE_DATA"
LINESPLAN_2D_STICKY_KEY = "MODEL_112_LINESPLAN_2D_IDS"
FORM_STICKY_KEY = "MODEL_112_MAIN_FORM"
START_PAGE_STICKY_KEY = "MODEL_112_START_PAGE"


def delete_object_ids(object_ids):
    if object_ids is None:
        return

    for object_id in list(object_ids):
        try:
            sc.doc.Objects.Delete(
                object_id,
                True
            )
        except Exception:
            pass


def clear_sticky_objects(sticky_key):
    object_ids = sc.sticky.get(
        sticky_key,
        []
    )

    delete_object_ids(
        object_ids
    )

    sc.sticky[sticky_key] = []


def delete_document_objects_created_since(
    before_ids
):
    """
    Dọn phần hình học sinh dở khi một thao tác lỗi giữa chừng.
    Chỉ xóa object xuất hiện sau snapshot trước thao tác.
    """
    try:
        after_ids = all_document_object_ids()
    except Exception:
        return []

    new_ids = list(
        after_ids.difference(
            set(
                before_ids or []
            )
        )
    )

    delete_object_ids(
        new_ids
    )

    return new_ids


def transform_object_ids(object_ids, transform):
    if transform is None:
        return list(object_ids)

    transformed_ids = []

    for object_id in object_ids:
        try:
            transformed_id = (
                sc.doc.Objects.Transform(
                    object_id,
                    transform,
                    True
                )
            )

            if (
                transformed_id is not None and
                transformed_id != System.Guid.Empty
            ):
                transformed_ids.append(
                    transformed_id
                )
        except Exception:
            transformed_ids.append(
                object_id
            )

    return transformed_ids



def split_created_ids_by_geometry_type(object_ids):
    """
    Phân loại object vừa tạo.

    Trả:
        framework_ids : Curve / Point / object không phải Brep
        surface_ids   : Brep (Surface / Polysurface)

    Việc phân loại được thực hiện SAU transform nên dùng đúng GUID hiện tại.
    """
    framework_ids = []
    surface_ids = []

    for object_id in object_ids or []:
        try:
            rhino_object = sc.doc.Objects.FindId(
                object_id
            )
        except Exception:
            rhino_object = None

        if rhino_object is None:
            continue

        geometry = rhino_object.Geometry

        if isinstance(
            geometry,
            rg.Brep
        ):
            surface_ids.append(
                object_id
            )
        else:
            framework_ids.append(
                object_id
            )

    return (
        framework_ids,
        surface_ids
    )



def group_object_ids(object_ids, group_name):
    if not object_ids:
        return -1

    try:
        group_index = sc.doc.Groups.Add(
            group_name
        )

        for object_id in object_ids:
            sc.doc.Groups.AddToGroup(
                group_index,
                object_id
            )

        return group_index
    except Exception:
        return -1



def build_hull_feature_level_labels(
    active_knuckle_count
):
    labels = [
        "Keel"
    ]

    if active_knuckle_count >= 1:
        labels.append(
            "Chine_01_Lower"
        )

    if active_knuckle_count >= 2:
        labels.append(
            "Chine_02_UpperInner"
        )

    if active_knuckle_count >= 3:
        labels.append(
            "Chine_03_UpperOuter"
        )

    labels.append(
        "Sheer"
    )

    return labels


def hull_feature_layer_for_label(
    label
):
    if label == "Keel":
        return LAYER_HULL_KEEL

    if label == "Sheer":
        return LAYER_HULL_SHEER

    return (
        LAYER_HULL_CHINES +
        u"::" +
        label
    )


def object_full_layer_path(
    object_id
):
    try:
        rhino_object = sc.doc.Objects.FindId(
            object_id
        )

        if rhino_object is None:
            return u""

        layer = sc.doc.Layers[
            rhino_object.Attributes.LayerIndex
        ]

        try:
            return layer.FullPath
        except Exception:
            return layer.Name
    except Exception:
        return u""


def split_created_ids_for_final_grouping(
    object_ids
):
    """
    Chỉ object đúng layer "khung" được group.
    Keel/Chine/Sheer và Surface được giữ độc lập.
    """
    framework_ids = []
    hull_feature_ids = []
    surface_ids = []
    other_ids = []

    for object_id in object_ids or []:
        try:
            rhino_object = sc.doc.Objects.FindId(
                object_id
            )
        except Exception:
            rhino_object = None

        if rhino_object is None:
            continue

        geometry = rhino_object.Geometry

        if isinstance(
            geometry,
            rg.Brep
        ):
            surface_ids.append(
                object_id
            )
            continue

        layer_path = object_full_layer_path(
            object_id
        )

        if layer_path == LAYER_KHUNG:
            framework_ids.append(
                object_id
            )
        elif layer_path.startswith(
            LAYER_HULL_LINES_ROOT
        ):
            hull_feature_ids.append(
                object_id
            )
        else:
            other_ids.append(
                object_id
            )

    return (
        framework_ids,
        hull_feature_ids,
        surface_ids,
        other_ids
    )



def midpoint_on_centerplane(
    port_point,
    starboard_point
):
    """
    Với hình học đối xứng, trung điểm của hai điểm port/starboard
    là điểm nằm đúng trên mặt phẳng dọc tâm Y = 0.
    """
    return rg.Point3d(
        0.5 * (
            port_point.X +
            starboard_point.X
        ),
        0.0,
        0.5 * (
            port_point.Z +
            starboard_point.Z
        )
    )


def create_center_tween_curve(
    port_curve,
    starboard_curve,
    label
):
    """
    Tạo curve ở giữa hai curve đối xứng.

    Ưu tiên Curve.CreateTweenCurves.
    Nếu Rhino không tạo được tween, dùng bản sao Starboard và ép Y về 0.
    """
    if (
        port_curve is None or
        starboard_curve is None
    ):
        return None

    tolerance = max(
        sc.doc.ModelAbsoluteTolerance,
        1.0e-9
    )

    try:
        tween_curves = rg.Curve.CreateTweenCurves(
            port_curve,
            starboard_curve,
            1,
            tolerance
        )

        if (
            tween_curves and
            len(tween_curves) > 0
        ):
            return tween_curves[0]
    except Exception:
        pass

    try:
        center_curve = (
            starboard_curve.DuplicateCurve()
        )

        flatten = rg.Transform.Identity
        flatten.M11 = 0.0

        center_curve.Transform(
            flatten
        )

        return center_curve
    except Exception as error:
        print(
            (
                "%s center curve failed: %s"
            ) % (
                label,
                str(error)
            )
        )

    return None


def add_transom_frame_geometry(
    port_level_points,
    starboard_level_points,
    force_create=False
):
    """
    Tạo wireframe của vách đuôi tại section đầu tiên.

    Full hull:
    - các đường ngang level từ Port -> Starboard;
    - biên Port và biên Starboard.

    Half hull:
    - các đường level từ Centerline -> Starboard;
    - biên Starboard;
    - thêm Centerline của nửa vách.
    """
    if (
        not ShowTransomFrame and
        not force_create
    ):
        return []

    # Tạo các layer theo đúng thứ tự ở panel Rhino: Keel, Chines, Sheer, TransomFrame.
    for layer_name in (LAYER_HULL_KEEL, LAYER_HULL_CHINES,
                       LAYER_HULL_SHEER, LAYER_TRANSOM_FRAME):
        ensure_model_layer_path(layer_name)

    frame_ids = []
    tolerance = max(
        sc.doc.ModelAbsoluteTolerance,
        1.0e-9
    )

    level_count = min(
        len(port_level_points),
        len(starboard_level_points)
    )

    if level_count < 2:
        return frame_ids

    port_stern = []
    starboard_stern = []
    center_stern = []

    for level_index in range(
        level_count
    ):
        p = port_level_points[
            level_index
        ][0]
        s = starboard_level_points[
            level_index
        ][0]
        c = midpoint_on_centerplane(
            p,
            s
        )

        port_stern.append(
            p
        )
        starboard_stern.append(
            s
        )
        center_stern.append(
            c
        )

        start_point = (
            c
            if CreateHalfModel
            else p
        )

        if start_point.DistanceTo(
            s
        ) > tolerance:
            object_id = add_curve_on_layer(
                rg.LineCurve(
                    start_point,
                    s
                ),
                LAYER_TRANSOM_FRAME
            )

            if object_id is not None:
                frame_ids.append(
                    object_id
                )

    for level_index in range(
        level_count - 1
    ):
        s0 = starboard_stern[
            level_index
        ]
        s1 = starboard_stern[
            level_index + 1
        ]

        if s0.DistanceTo(
            s1
        ) > tolerance:
            object_id = add_curve_on_layer(
                rg.LineCurve(
                    s0,
                    s1
                ),
                LAYER_TRANSOM_FRAME
            )

            if object_id is not None:
                frame_ids.append(
                    object_id
                )

        if CreateHalfModel:
            c0 = center_stern[
                level_index
            ]
            c1 = center_stern[
                level_index + 1
            ]

            if c0.DistanceTo(
                c1
            ) > tolerance:
                object_id = add_curve_on_layer(
                    rg.LineCurve(
                        c0,
                        c1
                    ),
                    LAYER_TRANSOM_FRAME
                )

                if object_id is not None:
                    frame_ids.append(
                        object_id
                    )
        else:
            p0 = port_stern[
                level_index
            ]
            p1 = port_stern[
                level_index + 1
            ]

            if p0.DistanceTo(
                p1
            ) > tolerance:
                object_id = add_curve_on_layer(
                    rg.LineCurve(
                        p0,
                        p1
                    ),
                    LAYER_TRANSOM_FRAME
                )

                if object_id is not None:
                    frame_ids.append(
                        object_id
                    )

    return frame_ids


def generate_hull(
    params,
    transform=None,
    group_name=None,
    sticky_key=None,
    clear_sticky=False,
    register_linesplan_sources=False
):
    global CURRENT_CREATED_IDS

    if (
        clear_sticky and
        sticky_key is not None
    ):
        clear_sticky_objects(
            sticky_key
        )

    ensure_document_units_match_parameters(
        params,
        u"tạo hình học"
    )

    apply_parameter_bindings(
        params
    )

    print(
        (
            "UNITS | Document=%s | "
            "1 m = %.9g model units | L=%.3f m | B=%.3f m | T=%.3f m"
        ) % (
            document_unit_name(),
            float(params.units_per_meter),
            model_units_to_meters(params.length, params.units_per_meter),
            model_units_to_meters(params.beam, params.units_per_meter),
            model_units_to_meters(params.draft, params.units_per_meter)
        )
    )

    CURRENT_CREATED_IDS = []

    errors = validate_parameters()

    if len(errors) > 0:
        raise Exception(
            "\n".join(
                errors
            )
        )

    keel_width = DERIVED.keel_width
    half_keel_width = DERIVED.half_keel_width

    keel_exists = (
        keel_width >
        max(
            1.0e-9,
            model_units_from_mm(
                0.01,
                params.units_per_meter
            )
        )
    )

    (
        starboard_keel_body,
        starboard_stem,
        starboard_keel_exact,
        starboard_keel_body_design_points,
        starboard_stem_design_points
    ) = create_keel_side(
        half_keel_width
    )

    (
        port_keel_body,
        port_stem,
        port_keel_exact,
        port_keel_body_design_points,
        port_stem_design_points
    ) = create_keel_side(
        -half_keel_width
    )

    body_station_ratios = (
        create_body_station_ratios()
    )

    bow_progress_values = (
        create_bow_progress_values()
    )

    (
        section_kinds,
        bow_progress_by_section
    ) = create_section_metadata(
        int(BodyStationCount),
        bow_progress_values
    )

    starboard_lower_join = (
        point_on_curve_at_z(
            starboard_stem,
            LowerChineBowEndHeight
        )
    )

    port_lower_join = (
        point_on_curve_at_z(
            port_stem,
            LowerChineBowEndHeight
        )
    )

    starboard_upper_join = (
        point_on_curve_at_z(
            starboard_stem,
            H *
            UpperChineStemJoinHeightRatio
        )
    )

    port_upper_join = (
        point_on_curve_at_z(
            port_stem,
            H *
            UpperChineStemJoinHeightRatio
        )
    )

    starboard_sheer_join = (
        point_on_curve_at_z(
            starboard_stem,
            H *
            SheerStemJoinHeightRatio
        )
    )

    port_sheer_join = (
        point_on_curve_at_z(
            port_stem,
            H *
            SheerStemJoinHeightRatio
        )
    )

    starboard_keel_body_points = []
    port_keel_body_points = []

    starboard_lower_body_points = []
    port_lower_body_points = []

    starboard_upper_inner_body_points = []
    port_upper_inner_body_points = []

    starboard_upper_outer_body_points = []
    port_upper_outer_body_points = []

    starboard_sheer_body_points = []
    port_sheer_body_points = []

    for body_index, x_ratio in enumerate(
        body_station_ratios
    ):
        if (
            body_index == 0 and
            CreateRakedBrokenTransom
        ):
            raw_keel_point = point_on_curve_at_x(
                starboard_keel_exact,
                0.0
            )

            raw_lower_point = (
                lower_chine_body_point(
                    1.0,
                    0.0,
                    half_keel_width
                )
            )

            raw_upper_inner_point = (
                upper_chine_inner_body_point(
                    1.0,
                    0.0
                )
            )

            raw_upper_outer_point = (
                upper_chine_outer_body_point(
                    raw_upper_inner_point,
                    1.0
                )
            )

            raw_sheer_point = (
                sheer_body_point(
                    1.0,
                    0.0
                )
            )

            keel_x = transom_level_x(
                "keel",
                raw_keel_point.Z,
                raw_keel_point.Z
            )

            lower_x = transom_level_x(
                "lower",
                raw_lower_point.Z,
                raw_keel_point.Z
            )

            upper_inner_x = (
                transom_level_x(
                    "upper_inner",
                    raw_upper_inner_point.Z,
                    raw_keel_point.Z
                )
            )

            upper_outer_x = (
                transom_level_x(
                    "upper_outer",
                    raw_upper_outer_point.Z,
                    raw_keel_point.Z
                )
            )

            sheer_x = transom_level_x(
                "sheer",
                raw_sheer_point.Z,
                raw_keel_point.Z
            )

            starboard_keel_point = (
                point_on_curve_at_x(
                    starboard_keel_exact,
                    keel_x
                )
            )

            port_keel_point = (
                point_on_curve_at_x(
                    port_keel_exact,
                    keel_x
                )
            )

            starboard_lower_point = (
                lower_chine_body_point(
                    1.0,
                    lower_x / L,
                    half_keel_width
                )
            )

            port_lower_point = (
                lower_chine_body_point(
                    -1.0,
                    lower_x / L,
                    half_keel_width
                )
            )

            starboard_inner_point = (
                upper_chine_inner_body_point(
                    1.0,
                    upper_inner_x / L
                )
            )

            port_inner_point = (
                upper_chine_inner_body_point(
                    -1.0,
                    upper_inner_x / L
                )
            )

            starboard_outer_reference = (
                upper_chine_inner_body_point(
                    1.0,
                    upper_outer_x / L
                )
            )

            port_outer_reference = (
                upper_chine_inner_body_point(
                    -1.0,
                    upper_outer_x / L
                )
            )

            starboard_outer_point = (
                upper_chine_outer_body_point(
                    starboard_outer_reference,
                    1.0
                )
            )

            port_outer_point = (
                upper_chine_outer_body_point(
                    port_outer_reference,
                    -1.0
                )
            )

            starboard_sheer_point = (
                sheer_body_point(
                    1.0,
                    sheer_x / L
                )
            )

            port_sheer_point = (
                sheer_body_point(
                    -1.0,
                    sheer_x / L
                )
            )
        else:
            x_value = L * x_ratio

            starboard_keel_point = (
                point_on_curve_at_x(
                    starboard_keel_exact,
                    x_value
                )
            )

            port_keel_point = (
                point_on_curve_at_x(
                    port_keel_exact,
                    x_value
                )
            )

            starboard_lower_point = (
                lower_chine_body_point(
                    1.0,
                    x_ratio,
                    half_keel_width
                )
            )

            port_lower_point = (
                lower_chine_body_point(
                    -1.0,
                    x_ratio,
                    half_keel_width
                )
            )

            starboard_inner_point = (
                upper_chine_inner_body_point(
                    1.0,
                    x_ratio
                )
            )

            port_inner_point = (
                upper_chine_inner_body_point(
                    -1.0,
                    x_ratio
                )
            )

            starboard_outer_point = (
                upper_chine_outer_body_point(
                    starboard_inner_point,
                    1.0
                )
            )

            port_outer_point = (
                upper_chine_outer_body_point(
                    port_inner_point,
                    -1.0
                )
            )

            starboard_sheer_point = (
                sheer_body_point(
                    1.0,
                    x_ratio
                )
            )

            port_sheer_point = (
                sheer_body_point(
                    -1.0,
                    x_ratio
                )
            )

        starboard_keel_body_points.append(
            starboard_keel_point
        )

        port_keel_body_points.append(
            port_keel_point
        )

        starboard_lower_body_points.append(
            starboard_lower_point
        )

        port_lower_body_points.append(
            port_lower_point
        )

        starboard_upper_inner_body_points.append(
            starboard_inner_point
        )

        port_upper_inner_body_points.append(
            port_inner_point
        )

        starboard_upper_outer_body_points.append(
            starboard_outer_point
        )

        port_upper_outer_body_points.append(
            port_outer_point
        )

        starboard_sheer_body_points.append(
            starboard_sheer_point
        )

        port_sheer_body_points.append(
            port_sheer_point
        )

    starboard_keel_points = (
        create_exact_curve_bow_points(
            starboard_keel_exact,
            starboard_keel_body_points,
            starboard_lower_join,
            bow_progress_values
        )
    )

    port_keel_points = (
        create_exact_curve_bow_points(
            port_keel_exact,
            port_keel_body_points,
            port_lower_join,
            bow_progress_values
        )
    )

    starboard_lower_points = (
        create_bow_bezier_points(
            starboard_lower_body_points,
            starboard_lower_join,
            bow_progress_values,
            0.24
        )
    )

    port_lower_points = (
        create_bow_bezier_points(
            port_lower_body_points,
            port_lower_join,
            bow_progress_values,
            0.24
        )
    )

    starboard_upper_inner_points = (
        create_bow_bezier_points(
            starboard_upper_inner_body_points,
            starboard_upper_join,
            bow_progress_values,
            0.62
        )
    )

    port_upper_inner_points = (
        create_bow_bezier_points(
            port_upper_inner_body_points,
            port_upper_join,
            bow_progress_values,
            0.62
        )
    )

    starboard_upper_outer_points = (
        create_upper_outer_points(
            starboard_upper_inner_points,
            1.0,
            int(BodyStationCount),
            bow_progress_values,
            starboard_upper_outer_body_points
        )
    )

    port_upper_outer_points = (
        create_upper_outer_points(
            port_upper_inner_points,
            -1.0,
            int(BodyStationCount),
            bow_progress_values,
            port_upper_outer_body_points
        )
    )

    starboard_sheer_points = (
        create_bow_bezier_points(
            starboard_sheer_body_points,
            starboard_sheer_join,
            bow_progress_values,
            1.00,
            SheerBowEntryHandleRatio,
            SheerBowStemHandleRatio,
            SheerBowStemControlOutboardFraction,
            SheerBowStemControlHeightFraction,
            SheerBowEntryVerticalTangentScale
        )
    )

    port_sheer_points = (
        create_bow_bezier_points(
            port_sheer_body_points,
            port_sheer_join,
            bow_progress_values,
            1.00,
            SheerBowEntryHandleRatio,
            SheerBowStemHandleRatio,
            SheerBowStemControlOutboardFraction,
            SheerBowStemControlHeightFraction,
            SheerBowEntryVerticalTangentScale
        )
    )

    starboard_extra_points = []
    port_extra_points = []

    active_knuckle_count = int(TotalKnuckleCountPerSide)

    extra_knuckle_count = max(
        0,
        active_knuckle_count - 3
    )

    for extra_index in range(
        extra_knuckle_count
    ):
        fraction = (
            float(extra_index + 1) /
            float(extra_knuckle_count + 1)
        )

        starboard_extra_points.append(
            create_extra_rail_points(
                1.0,
                fraction,
                starboard_upper_outer_body_points,
                starboard_sheer_body_points,
                starboard_stem,
                bow_progress_values
            )
        )

        port_extra_points.append(
            create_extra_rail_points(
                -1.0,
                fraction,
                port_upper_outer_body_points,
                port_sheer_body_points,
                port_stem,
                bow_progress_values
            )
        )

    validate_monotonic_bow(
        starboard_lower_points,
        "Starboard lower chine",
        1.0,
        int(BodyStationCount)
    )

    validate_monotonic_bow(
        port_lower_points,
        "Port lower chine",
        -1.0,
        int(BodyStationCount)
    )

    validate_monotonic_bow(
        starboard_upper_inner_points,
        "Starboard upper inner chine",
        1.0,
        int(BodyStationCount)
    )

    validate_monotonic_bow(
        port_upper_inner_points,
        "Port upper inner chine",
        -1.0,
        int(BodyStationCount)
    )

    validate_monotonic_bow(
        starboard_sheer_points,
        "Starboard sheer",
        1.0,
        int(BodyStationCount)
    )

    validate_monotonic_bow(
        port_sheer_points,
        "Port sheer",
        -1.0,
        int(BodyStationCount)
    )

    validate_upper_chine_gap(
        starboard_upper_inner_points,
        starboard_upper_outer_points,
        int(BodyStationCount)
    )

    validate_upper_chine_gap(
        port_upper_inner_points,
        port_upper_outer_points,
        int(BodyStationCount)
    )

    # Chọn số rail trung gian theo số đường gãy góc 1-3.
    # 1: keel -> lower chine -> sheer; 2: thêm upper inner;
    # 3: thêm upper outer.
    starboard_level_points = [
        starboard_keel_points
    ]
    port_level_points = [
        port_keel_points
    ]

    if active_knuckle_count >= 1:
        starboard_level_points.append(
            starboard_lower_points
        )
        port_level_points.append(
            port_lower_points
        )

    if active_knuckle_count >= 2:
        starboard_level_points.append(
            starboard_upper_inner_points
        )
        port_level_points.append(
            port_upper_inner_points
        )

    if active_knuckle_count >= 3:
        starboard_level_points.append(
            starboard_upper_outer_points
        )
        port_level_points.append(
            port_upper_outer_points
        )

    if active_knuckle_count >= 4:
        for points in starboard_extra_points:
            starboard_level_points.append(
                points
            )

        for points in port_extra_points:
            port_level_points.append(
                points
            )

    starboard_level_points.append(
        starboard_sheer_points
    )

    port_level_points.append(
        port_sheer_points
    )

    station_records = build_station_records(
        section_kinds,
        starboard_level_points
    )

    export_paths = []
    export_run_token = build_export_run_token()

    if ExportParameterTable:
        export_paths.append(
            export_parameter_catalog(
                export_run_token
            )
        )

    if ExportStationTable:
        export_paths.append(
            export_station_records(
                station_records,
                export_run_token
            )
        )

    print_parameter_method_summary()

    # Số panel luôn bằng số level - 1.
    if active_knuckle_count == 0:
        panel_kinds = [
            "upper_side"
        ]
    elif active_knuckle_count == 1:
        panel_kinds = [
            "bottom",
            "upper_side"
        ]
    elif active_knuckle_count == 2:
        panel_kinds = [
            "bottom",
            "lower_side",
            "upper_side"
        ]
    else:
        panel_kinds = [
            "bottom",
            "lower_side",
            "upper_band"
        ]

        for extra_index in range(
            extra_knuckle_count
        ):
            panel_kinds.append(
                "upper_side"
            )

        panel_kinds.append(
            "upper_side"
        )

    starboard_level_curves = []
    port_level_curves = []

    for points in starboard_level_points:
        starboard_level_curves.append(
            create_interp_curve(
                points,
                CurveDegree
            )
        )

    for points in port_level_points:
        port_level_curves.append(
            create_interp_curve(
                points,
                CurveDegree
            )
        )

    # -----------------------------------------------------------------
    # KEEL / CHINE / SHEER được tách khỏi "khung".
    # Vỏ cuối luôn tạo các đường này để Trang 4 có nguồn 2D.
    # Nếu ShowLongitudinalCurves=False thì chỉ Hide, không xóa.
    # -----------------------------------------------------------------
    hull_line_records = []
    hull_line_all_ids = []

    create_hull_feature_objects = bool(
        ShowLongitudinalCurves or
        register_linesplan_sources
    )

    if create_hull_feature_objects:
        feature_labels = build_hull_feature_level_labels(
            active_knuckle_count
        )

        # Với Bk=0 vẫn giữ đúng một đường keel dọc tâm tàu (Y=0).
        # Nửa thân chỉ giữ mạn phải; Bk>0 toàn thân giữ hai mép keel.
        starboard_keel_id = add_curve_on_layer(
            starboard_keel_exact,
            LAYER_HULL_KEEL
        )

        port_keel_id = None
        if keel_exists and not CreateHalfModel:
            port_keel_id = add_curve_on_layer(
                port_keel_exact,
                LAYER_HULL_KEEL
            )

        keel_ids = [
            object_id
            for object_id in [port_keel_id, starboard_keel_id]
            if object_id is not None
        ]

        if keel_ids:
            hull_line_all_ids.extend(keel_ids)
            hull_line_records.append(
                {
                    "label": "Keel",
                    "kind": "Keel",
                    "profile_ids": (
                        [starboard_keel_id]
                        if starboard_keel_id is not None
                        else list(keel_ids[:1])
                    ),
                    "plan_ids": list(keel_ids),
                    "body_ids": list(keel_ids),
                    "all_ids": list(keel_ids)
                }
            )

        for level_index in range(
            1,
            len(
                starboard_level_curves
            )
        ):
            label = feature_labels[
                level_index
            ]

            layer_name = hull_feature_layer_for_label(
                label
            )

            starboard_id = add_curve_on_layer(
                starboard_level_curves[
                    level_index
                ],
                layer_name
            )

            port_id = None

            if not CreateHalfModel:
                port_id = add_curve_on_layer(
                    port_level_curves[
                        level_index
                    ],
                    layer_name
                )

            pair_ids = [
                object_id
                for object_id in [
                    port_id,
                    starboard_id
                ]
                if object_id is not None
            ]

            hull_line_all_ids.extend(
                pair_ids
            )

            hull_line_records.append(
                {
                    "label": label,
                    "kind": (
                        "Sheer"
                        if label == "Sheer"
                        else "Chine"
                    ),
                    # Front: chỉ một mạn để tránh chồng curve.
                    "profile_ids": (
                        [starboard_id]
                        if starboard_id is not None
                        else list(pair_ids[:1])
                    ),
                    # Top: giữ hai mạn.
                    "plan_ids": list(
                        pair_ids
                    ),
                    "body_ids": list(
                        pair_ids
                    ),
                    "all_ids": list(
                        pair_ids
                    )
                }
            )

        # -------------------------------------------------------------
        # HIỂN THỊ RIÊNG TỪNG HỌ ĐƯỜNG.
        # Các curve vẫn được giữ khi register_linesplan_sources=True
        # để Trang 4 có thể dùng làm nguồn Make2D.
        # -------------------------------------------------------------
        for record in hull_line_records:
            kind = record.get(
                "kind",
                ""
            )

            should_show = True

            if kind == "Keel":
                should_show = bool(
                    ShowKeelCurve
                )
            elif kind == "Chine":
                should_show = bool(
                    ShowChineCurves
                )
            elif kind == "Sheer":
                should_show = bool(
                    ShowSheerCurve
                )

            set_objects_hidden(
                record.get(
                    "all_ids",
                    []
                ),
                not should_show
            )

    transom_frame_ids = add_transom_frame_geometry(
        port_level_points,
        starboard_level_points,
        force_create=bool(
            register_linesplan_sources
        )
    )

    # Transom is a real hull feature for Mode 2. Register the same 3D
    # geometry used by Mode 1 so Profile / Half-Breadth / Body Plan all
    # receive the transom when Make2D is created.
    if transom_frame_ids:
        transom_ids = list(
            transom_frame_ids
        )

        hull_line_records.append(
            {
                "label": "Transom",
                "kind": "Transom",
                "profile_ids": list(
                    transom_ids
                ),
                "plan_ids": list(
                    transom_ids
                ),
                "body_ids": list(
                    transom_ids
                ),
                "all_ids": list(
                    transom_ids
                )
            }
        )

        hull_line_all_ids.extend(
            transom_ids
        )

        # If the user does not want the transom frame visible in Mode 1,
        # keep it hidden there. Mode 2 still duplicates the geometry and
        # uses it as a Make2D source.
        if not ShowTransomFrame:
            set_objects_hidden(
                transom_ids,
                True
            )

    hull_line_data = {
        "records": hull_line_records,
        "all_ids": hull_line_all_ids
    }

    show_station_geometry(
        port_level_points,
        starboard_level_points,
        section_kinds,
        bow_progress_by_section,
        panel_kinds
    )

    design_point_groups = []

    design_point_groups.extend(
        starboard_level_points
    )

    if not CreateHalfModel:
        design_point_groups.extend(
            port_level_points
        )

    add_design_points(
        design_point_groups
    )

    hull_breps = []
    surface_report = []

    if CreateHullSurfaces:
        if keel_exists:
            if CreateHalfModel:
                center_keel_body = create_center_tween_curve(
                    port_keel_body,
                    starboard_keel_body,
                    "Half keel body"
                )

                keel_body_strip = create_ruled_surface(
                    center_keel_body,
                    starboard_keel_body,
                    "Half keel body strip"
                )
            else:
                keel_body_strip = create_ruled_surface(
                    port_keel_body,
                    starboard_keel_body,
                    "Keel body strip"
                )

            if keel_body_strip is not None:
                hull_breps.append(
                    keel_body_strip
                )

                surface_report.append(
                    "Keel body strip: ruled"
                )
        else:
            surface_report.append(
                "Keel body strip: omitted (Bk = 0)"
            )

        # Forefoot strip giữa hai mép keel chỉ tồn tại khi Bk > 0.
        if (
            active_knuckle_count >= 1 and
            keel_exists
        ):
            port_forefoot_curve = trim_curve_between_points(
                port_stem,
                port_stem.PointAtStart,
                port_lower_join,
                "Port forefoot stem"
            )

            starboard_forefoot_curve = trim_curve_between_points(
                starboard_stem,
                starboard_stem.PointAtStart,
                starboard_lower_join,
                "Starboard forefoot stem"
            )

            if CreateHalfModel:
                center_forefoot_curve = create_center_tween_curve(
                    port_forefoot_curve,
                    starboard_forefoot_curve,
                    "Half forefoot"
                )

                forefoot_stem_strip = create_ruled_surface(
                    center_forefoot_curve,
                    starboard_forefoot_curve,
                    "Half forefoot stem strip"
                )
            else:
                forefoot_stem_strip = create_ruled_surface(
                    port_forefoot_curve,
                    starboard_forefoot_curve,
                    "Forefoot stem strip"
                )

            if forefoot_stem_strip is not None:
                hull_breps.append(
                    forefoot_stem_strip
                )

                surface_report.append(
                    "Forefoot stem strip: ruled"
                )

        side_indices = (
            [1]
            if CreateHalfModel
            else range(2)
        )

        for side_index in side_indices:
            if side_index == 0:
                side_sign = -1.0
                side_name = "Port"
                level_points = (
                    port_level_points
                )
                level_curves = (
                    port_level_curves
                )
                lower_join_point = (
                    port_lower_join
                )
                keel_body_curve = (
                    port_keel_body
                )

                keel_exact_curve = (
                    port_keel_exact
                )
                stem_curve = (
                    port_stem
                )
            else:
                side_sign = 1.0
                side_name = "Starboard"
                level_points = (
                    starboard_level_points
                )
                level_curves = (
                    starboard_level_curves
                )
                lower_join_point = (
                    starboard_lower_join
                )
                keel_body_curve = (
                    starboard_keel_body
                )

                keel_exact_curve = (
                    starboard_keel_exact
                )
                stem_curve = (
                    starboard_stem
                )

            # -------------------------------------------------------------
                    
            # Khi ForceSharedLowerChineEdge=True, TUYỆT ĐỐI không đi vào
            # create_split_bottom_panels() vì nhánh này loft bottom riêng và
            # sinh ra hai edge lower-chine không trùng với lower-side.
            # -------------------------------------------------------------
            if (
                SplitBottomAtKeelStem and
                not ForceSharedLowerChineEdge
            ):
                (
                    bottom_body_panel,
                    bottom_forefoot_panel,
                    bottom_split_section
                ) = create_split_bottom_panels(
                    side_name,
                    side_sign,
                    level_points[0],
                    level_points[1],
                    level_curves[1],
                    keel_body_curve,
                    stem_curve,
                    lower_join_point,
                    section_kinds,
                    bow_progress_by_section
                )

                if bottom_body_panel is not None:
                    hull_breps.append(
                        bottom_body_panel
                    )

                    surface_report.append(
                        side_name +
                        " bottom body: loft"
                    )

                if bottom_forefoot_panel is not None:
                    hull_breps.append(
                        bottom_forefoot_panel
                    )

                    surface_report.append(
                        side_name +
                        " bottom forefoot: loft"
                    )

            if ForceSharedLowerChineEdge:
                print(
                    "topology %s | bottom=continuous | "
                    "lower_side=continuous | lower_chine=shared rail" %
                    side_name
                )

            for panel_index in range(
                len(panel_kinds)
            ):
                if (
                    SplitBottomAtKeelStem and
                    not ForceSharedLowerChineEdge and
                    panel_index == 0
                ):
                    continue
                panel_kind = (
                    panel_kinds[
                        panel_index
                    ]
                )

                lower_points = (
                    level_points[
                        panel_index
                    ]
                )

                upper_points = (
                    level_points[
                        panel_index + 1
                    ]
                )

                panel_name = (
                    "%s panel %d %s" %
                    (
                        side_name,
                        panel_index,
                        panel_kind
                    )
                )

                if (
                    SplitSidePanelsAtBow and
                    panel_kind != "bottom" and
                    not (
                        ForceSharedLowerChineEdge and
                        panel_kind == "lower_side"
                    )
                ):
                    (
                        body_panel,
                        bow_panel,
                        side_split_section
                    ) = create_split_side_panels(
                        side_name,
                        side_sign,
                        panel_kind,
                        lower_points,
                        upper_points,
                        section_kinds,
                        bow_progress_by_section
                    )

                    if body_panel is not None:
                        hull_breps.append(
                            body_panel
                        )

                        surface_report.append(
                            panel_name +
                            " body: loft"
                        )

                    if bow_panel is not None:
                        hull_breps.append(
                            bow_panel
                        )

                        surface_report.append(
                            panel_name +
                            " bow: loft"
                        )
                else:
                    section_curves = []

                            
                    # Có thể có thêm Brep phụ cho phần forefoot đóng mũi.
                    additional_panel_breps = []

                    end_distance = (
                        lower_points[-1].DistanceTo(
                            upper_points[-1]
                        )
                    )

                    collapse_end_point = None

                    if (
                        end_distance <=
                        sc.doc.ModelAbsoluteTolerance *
                        JoinToleranceFactor
                    ):
                        collapse_end_point = (
                            lower_points[-1]
                        )

                        final_section_index = (
                            len(section_kinds) -
                            1
                        )
                    else:
                        final_section_index = (
                            len(section_kinds)
                        )

                    for section_index in range(
                        final_section_index
                    ):
                        section_curve = create_section_curve(
                            lower_points[
                                section_index
                            ],
                            upper_points[
                                section_index
                            ],
                            side_sign,
                            panel_kind,
                            section_kinds[
                                section_index
                            ],
                            bow_progress_by_section[
                                section_index
                            ]
                        )

                        if section_curve is not None:
                            section_curves.append(
                                section_curve
                            )

                    # ---------------------------------------------------------
                                                
                    # ---------------------------------------------------------
                    # Chế độ 1 vẫn dùng Loft cũ.
                    # Chế độ 3 bật UseLongitudinalRailSurfaces và dùng chính
                    # các đường khung dọc làm hai biên bắt buộc của panel.
                    # ---------------------------------------------------------
                    # ---------------------------------------------------------
                            
                    # Dù Chế độ 1 không bật rail-surfaces toàn thân, riêng hai
                    # panel bottom và lower_side vẫn bắt buộc dùng rail thật.
                    #
                    # panel 0 (bottom):
                    #   keel_exact -> lower_chine
                    #
                    # panel 1 (lower_side):
                    #   lower_chine -> upper_chine
                    #
                    # Vì cả hai cùng dùng level_curves[1], biên lower-chine
                    # là cùng một geometry, không còn hai mép Loft độc lập.
                    # ---------------------------------------------------------
                    use_shared_chine_rail = (
                        ForceSharedLowerChineEdge and
                        active_knuckle_count >= 1 and
                        panel_index in (0, 1)
                    )

                    if (
                        UseLongitudinalRailSurfaces or
                        use_shared_chine_rail
                    ):
                        if panel_index == 0:
                            # Bottom:
                            # rail thấp là keel exact từ đuôi tới đúng điểm
                            # lower chine nhập vào sống mũi.
                            try:
                                lower_rail = trim_curve_between_points(
                                    keel_exact_curve,
                                    keel_exact_curve.PointAtStart,
                                    lower_join_point,
                                    side_name + " hydro keel rail"
                                )
                            except Exception:
                                lower_rail = level_curves[0]
                        else:
                            lower_rail = level_curves[
                                panel_index
                            ]

                        upper_rail = level_curves[
                            panel_index + 1
                        ]

                        panel_brep = (
                            create_panel_two_longitudinal_rails(
                                lower_rail,
                                upper_rail,
                                section_curves,
                                panel_name
                            )
                        )

                        # -----------------------------------------------------
                                                  
                        # -----------------------------------------------------
                        # Bottom có endpoint keel/lower-chine trùng nhau ở mũi,
                        # nên section cuối "stem" bị loại vì có chiều dài = 0.
                        # Sweep2 thường chỉ chạy tới section cuối không suy biến.
                        #
                        # Tạo thêm một patch chính xác từ section cuối đó tới
                        # lower_join_point để lấp kín đáy mũi.
                        # -----------------------------------------------------
                        if (
                            ForceSharedLowerChineEdge and
                            active_knuckle_count >= 1 and
                            panel_index == 0 and
                            len(section_curves) > 0
                        ):
                            forefoot_patch = (
                                create_bottom_forefoot_closure_patch(
                                    side_name,
                                    lower_rail,
                                    upper_rail,
                                    section_curves[-1],
                                    lower_join_point
                                )
                            )

                            if forefoot_patch is not None:
                                additional_panel_breps.append(
                                    forefoot_patch
                                )

                        if use_shared_chine_rail:
                            panel_method_text = (
                                ": Sweep2 rail chung lower-chine"
                            )
                        else:
                            panel_method_text = (
                                ": Sweep2 theo rail dọc"
                            )
                    else:
                        panel_brep = create_panel_loft(
                            section_curves,
                            panel_name,
                            collapse_end_point
                        )

                        panel_method_text = (
                            ": loft"
                        )

                    if panel_brep is not None:
                        hull_breps.append(
                            panel_brep
                        )

                        surface_report.append(
                            panel_name +
                            panel_method_text
                        )

                            
                    # Forefoot closure là object/mặt riêng để dễ ShowEdges và
                    # Join thủ công; nó vẫn nằm trên layer "mặt tàu".
                    for extra_brep in additional_panel_breps:
                        if extra_brep is None:
                            continue

                        hull_breps.append(
                            extra_brep
                        )

                        surface_report.append(
                            panel_name +
                            ": forefoot closure"
                        )

        unique_stem_levels = []

        for level_index in range(
            len(starboard_level_points)
        ):
            starboard_join_point = (
                starboard_level_points[
                    level_index
                ][-1]
            )

            port_join_point = (
                port_level_points[
                    level_index
                ][-1]
            )

            duplicate = False

            for existing_pair in unique_stem_levels:
                if (
                    existing_pair[0].DistanceTo(
                        port_join_point
                    ) <=
                    sc.doc.ModelAbsoluteTolerance *
                    JoinToleranceFactor and
                    existing_pair[1].DistanceTo(
                        starboard_join_point
                    ) <=
                    sc.doc.ModelAbsoluteTolerance *
                    JoinToleranceFactor
                ):
                    duplicate = True
                    break

            if not duplicate:
                unique_stem_levels.append(
                    (
                        port_join_point,
                        starboard_join_point
                    )
                )

        stem_front_sections = []

        for point_pair in unique_stem_levels:
            if CreateHalfModel:
                stem_center = midpoint_on_centerplane(
                    point_pair[0],
                    point_pair[1]
                )

                stem_front_sections.append(
                    rg.LineCurve(
                        stem_center,
                        point_pair[1]
                    )
                )
            else:
                stem_front_sections.append(
                    rg.LineCurve(
                        point_pair[0],
                        point_pair[1]
                    )
                )

        stem_front = create_panel_loft(
            stem_front_sections,
            "Stem front",
            None
        )

        if stem_front is not None:
            hull_breps.append(
                stem_front
            )

            surface_report.append(
                "Stem front: loft"
            )

    if (
        CreateHullSurfaces and
        ForceSharedLowerChineEdge
    ):
        print(
            "bottom + lower_side dung CHUNG lower-chine rail; "
            "bottom co them forefoot closure dung exact rails."
        )

    # Đường cắt 3D lấy từ vỏ mở. Nếu cắt cả các tấm vách đuôi rồi
    # JoinCurves, giao tuyến ngang trên vách có thể nối vào đầu đường
    # nước và tạo nhánh móc rất ngắn khi nhìn hình chiếu cạnh.
    # Thủy tĩnh vẫn dùng đủ các mặt bên dưới, kể cả vách đuôi.
    linesplan_brep_count = len(hull_breps)

    if CreateTransomSurfaces:
        for panel_index in range(
            len(panel_kinds)
        ):
            transom_port_lower = (
                port_level_points[
                    panel_index
                ][0]
            )
            transom_starboard_lower = (
                starboard_level_points[
                    panel_index
                ][0]
            )
            transom_port_upper = (
                port_level_points[
                    panel_index + 1
                ][0]
            )
            transom_starboard_upper = (
                starboard_level_points[
                    panel_index + 1
                ][0]
            )

            if CreateHalfModel:
                transom_center_lower = midpoint_on_centerplane(
                    transom_port_lower,
                    transom_starboard_lower
                )
                transom_center_upper = midpoint_on_centerplane(
                    transom_port_upper,
                    transom_starboard_upper
                )

                transom_panel_points = [
                    transom_center_lower,
                    transom_starboard_lower,
                    transom_starboard_upper,
                    transom_center_upper
                ]
            else:
                transom_panel_points = [
                    transom_port_lower,
                    transom_starboard_lower,
                    transom_starboard_upper,
                    transom_port_upper
                ]

            transom_panel = (
                create_planar_panel(
                    transom_panel_points,
                    "Transom panel %d" %
                    panel_index
                )
            )

            if transom_panel is not None:
                hull_breps.append(
                    transom_panel
                )

                surface_report.append(
                    "Transom panel %d: planar" %
                    panel_index
                )

    if CreateDeckSurface:
        deck_section_curves = []

        for section_index in range(
            len(section_kinds)
        ):
            deck_port = port_sheer_points[
                section_index
            ]
            deck_starboard = starboard_sheer_points[
                section_index
            ]

            deck_start = (
                midpoint_on_centerplane(
                    deck_port,
                    deck_starboard
                )
                if CreateHalfModel
                else deck_port
            )

            deck_section_curves.append(
                rg.LineCurve(
                    deck_start,
                    deck_starboard
                )
            )

        deck_surface = create_panel_loft(
            deck_section_curves,
            "Deck",
            None
        )

        if deck_surface is not None:
            hull_breps.append(
                deck_surface
            )

            surface_report.append(
                "Deck: loft"
            )

    joined_hull_breps = None

    if (
        JoinHullSurfaces and
        len(hull_breps) > 0
    ):
        joined_hull_breps = (
            rg.Brep.JoinBreps(
                hull_breps,
                sc.doc.ModelAbsoluteTolerance *
                JoinToleranceFactor
            )
        )

    if (
        joined_hull_breps and
        len(joined_hull_breps) > 0
    ):
        for joined_brep in joined_hull_breps:
            add_brep(
                joined_brep
            )

        print(
            "Joined hull Breps: %d" %
            len(joined_hull_breps)
        )

        for joined_brep in joined_hull_breps:
            naked_edges = (
                joined_brep.DuplicateNakedEdgeCurves(
                    True,
                    True
                )
            )

            print(
                "Solid: %s, naked edges: %d" %
                (
                    str(
                        joined_brep.IsSolid
                    ),
                    len(
                        naked_edges
                    )
                )
            )
    else:
        print(
            "Hull join failed or was disabled. V7.13: adding individual surfaces for kiểm tra thủ công."
        )

        if AddIndividualSurfacesWhenJoinFails:
            for hull_brep in hull_breps:
                add_brep(
                    hull_brep
                )

            print(
                "individual hull surfaces added: %d" %
                len(hull_breps)
            )

    for report_line in surface_report:
        print(
            report_line
        )

    if CreateDesignWaterline:
        waterline_z = (
            design_waterline_z()
        )

        waterline_y_min = (
            0.0
            if CreateHalfModel
            else -B * 0.5
        )

        waterline_points = [
            rg.Point3d(
                0.0,
                waterline_y_min,
                waterline_z
            ),
            rg.Point3d(
                L,
                waterline_y_min,
                waterline_z
            ),
            rg.Point3d(
                L,
                B * 0.5,
                waterline_z
            ),
            rg.Point3d(
                0.0,
                B * 0.5,
                waterline_z
            ),
            rg.Point3d(
                0.0,
                waterline_y_min,
                waterline_z
            )
        ]

        add_curve(
            rg.PolylineCurve(
                waterline_points
            )
        )

    print(
        "Body stations: %d" %
        int(BodyStationCount)
    )

    print(
        "Bow fairing sections: %d" %
        int(BowFairingSectionCount)
    )

    print(
        "Total sections: %d" %
        len(section_kinds)
    )

    print(
        "Knuckle lines per side: %d" %
        int(TotalKnuckleCountPerSide)
    )

    print(
        "Model version: %s" %
        ModelVersion
    )

    print(
        "Lower chine bow end height: %.3f" %
        LowerChineBowEndHeight
    )

    print(
        "Upper chine body height gap: %.3f" %
        UpperChineOuterHeightGap
    )

    print(
        "Upper chine body side gap: %.3f" %
        UpperChineOuterSideGap
    )

    print(
        "Bottom topology mode: %s" %
        BottomTopologyMode
    )

    print(
        "Transom rake angle: %.3f" %
        TransomRakeAngle
    )

    print(
        "Sheer sag depth: %.3f" %
        (
            H *
            SheerSagDepthRatio
        )
    )

    print(
        "Side panels split at bow: %s" %
        str(SplitSidePanelsAtBow)
    )

    print(
        "Bow body start ratio: %.3f" %
        BowBodyStartRatio
    )


    created_ids = list(
        CURRENT_CREATED_IDS
    )

    created_ids = transform_object_ids(
        created_ids,
        transform
    )

    CURRENT_CREATED_IDS = list(
        created_ids
    )

    # -----------------------------------------------------------------
                                 
    # -----------------------------------------------------------------
    # Group trong Rhino làm click một object có thể chọn toàn bộ group.
    # Điều này gây khó khăn khi kiểm tra mặt vỏ thủ công.
    #
    # Vì vậy:
    # - Curve / Point của "khung" vẫn có thể group để dễ quản lý.
    # - Brep / Surface của "mặt tàu" luôn để độc lập.
    # -----------------------------------------------------------------
    if group_name is not None:
        if GroupFrameworkOnly:
            (
                framework_ids,
                hull_feature_ids,
                surface_ids,
                other_ids
            ) = split_created_ids_for_final_grouping(
                created_ids
            )

            if framework_ids:
                group_object_ids(
                    framework_ids,
                    group_name + "_Khung"
                )

            print(
                (
                    "kiểm tra thủ công | "
                    "khung grouped=%d | hull lines independent=%d | "
                    "surfaces independent=%d | other=%d"
                ) % (
                    len(framework_ids),
                    len(hull_feature_ids),
                    len(surface_ids),
                    len(other_ids)
                )
            )
        else:
            group_object_ids(
                created_ids,
                group_name
            )

    if sticky_key is not None:
        sc.sticky[sticky_key] = list(
            created_ids
        )

    sc.doc.Views.Redraw()

    return {
        "object_ids": created_ids,
        "station_records": station_records,
        "surface_report": surface_report,
        "joined_hull_breps": joined_hull_breps,
                                                                          
        "hull_breps": hull_breps,
        "linesplan_brep_count": linesplan_brep_count,
        "hull_line_data": hull_line_data,
        "transom_frame_ids": transom_frame_ids,
        "export_paths": export_paths
    }





# =============================================================================
# MODULE 12B: TẠO HỆ ĐƯỜNG HÌNH 3D VÀ CHIẾU 2D
# =============================================================================
# Mục tiêu:
# - Cho phép người dùng chọn số lượng sườn, đường nước và đường cắt dọc.
# - Tạo các giao tuyến thật từ bề mặt vỏ tham số.
# - Gom nguồn 3D cố định vào 4 layer: Station / Waterline / Buttock / HullLine.
# - Tạo ba hình chiếu 2D và gom toàn bộ output vào DRAWING_2D.
#
# Quy ước hình chiếu / hệ trục:
# - Hình bằng (Top nhìn từ +Z xuống -Z): X = chiều dài, Y = chiều rộng.
# - Hình đứng (Profile): X = chiều dài, trục đứng biểu diễn Z = chiều cao.
# - Hình cạnh (Body Plan): trục ngang biểu diễn Y = chiều rộng, trục đứng = Z.
#
# Lưu ý:
# - Module này không yêu cầu vỏ phải là closed polysurface.
# - Nguồn cắt là tập Brep của vỏ được dựng từ chính bộ tham số hiện tại.
# - Make2D chỉ phục vụ trình bày; bảng tọa độ V19 đo trực tiếp trên SOURCE_3D.


LINESPLAN_ROOT = u"MODEL112::LINES_PLAN"

LINESPLAN_SOURCE_ROOT = (
    LINESPLAN_ROOT +
    u"::SOURCE_3D"
)
LINESPLAN_SOURCE_STATION = (
    LINESPLAN_SOURCE_ROOT +
    u"::Station"
)
LINESPLAN_SOURCE_WATERLINE = (
    LINESPLAN_SOURCE_ROOT +
    u"::Waterline"
)
LINESPLAN_SOURCE_BUTTOCK = (
    LINESPLAN_SOURCE_ROOT +
    u"::Buttock"
)
LINESPLAN_SOURCE_HULLLINES = (
    LINESPLAN_SOURCE_ROOT +
    u"::HullLine"
)


def model112_linesplan_source_object_ids():
    """Tìm cả nguồn 3D của phiên Rhino trước khi sticky bị làm mới."""
    ids = list(sc.sticky.get(LINESPLAN_SOURCE_STICKY_KEY, []) or [])
    try:
        layers = [
            name for name in (rs.LayerNames() or [])
            if name == LINESPLAN_SOURCE_ROOT or
            name.startswith(LINESPLAN_SOURCE_ROOT + u"::")
        ]
        for layer_name in layers:
            ids.extend(rs.ObjectsByLayer(layer_name) or [])
    except Exception:
        pass
    unique_ids = []
    seen = set()
    for object_id in ids:
        if object_id not in seen:
            seen.add(object_id)
            unique_ids.append(object_id)
    return unique_ids

LINESPLAN_DRAWING_ROOT = (
    LINESPLAN_ROOT +
    u"::DRAWING_2D"
)

# V19: toàn bộ bản vẽ 2D cuối cùng nằm trên MỘT layer duy nhất.
# Các sublayer cũ chỉ giữ tên để tương thích code/phiên bản cũ, không còn dùng
# để chứa output Make2D mới.
LINESPLAN_2D_OUTPUT_LAYER = LINESPLAN_DRAWING_ROOT
LINESPLAN_EXPORT_OUTPUT_LAYER = LINESPLAN_ROOT + u"::EXPORT_2D"
LINESPLAN_EXPORT_STICKY_KEY = "MODEL_112_LINESPLAN_EXPORT_2D_IDS"

LINESPLAN_PROFILE_BUTTOCK = (
    LINESPLAN_DRAWING_ROOT +
    u"::Profile::Buttocks"
)
LINESPLAN_PLAN_WATERLINE = (
    LINESPLAN_DRAWING_ROOT +
    u"::HalfBreadth::Waterlines"
)
LINESPLAN_BODY_STATION = (
    LINESPLAN_DRAWING_ROOT +
    u"::BodyPlan::Stations"
)
LINESPLAN_PROFILE_HULLLINES = (
    LINESPLAN_DRAWING_ROOT +
    u"::Profile::HullLines"
)
LINESPLAN_PLAN_HULLLINES = (
    LINESPLAN_DRAWING_ROOT +
    u"::HalfBreadth::HullLines"
)


def ensure_nested_layer(layer_path):
    return ensure_model_layer_path(
        layer_path
    )


def get_linesplan_layer_attributes(layer_path):
    layer_index = ensure_nested_layer(
        layer_path
    )

    if layer_index is None or layer_index < 0:
        return None

    attributes = Rhino.DocObjects.ObjectAttributes()
    attributes.LayerIndex = layer_index
    return attributes


def linesplan_value_label(
    prefix,
    index,
    axis_letter,
    value_model,
    units_per_meter
):
    value_m = (
        float(value_model) /
        float(units_per_meter)
    )

    return (
        u"%s_%02d_%s_%0.3fm" %
        (
            prefix,
            int(index),
            axis_letter,
            value_m
        )
    )


def linesplan_child_layer(
    parent_path,
    label,
    individual_layers
):
    """
    V19 luôn gom một họ đường 3D vào đúng một layer cha.

    Giữ đủ tham số để tương thích các lời gọi cũ, nhưng không còn tạo
    sublayer STA_XX / WL_XX / CD_XX.
    """
    return parent_path


def add_curve_to_named_layer(curve, layer_name):
    if curve is None:
        return None

    attributes = get_linesplan_layer_attributes(
        layer_name
    )

    try:
        if attributes is not None:
            object_id = sc.doc.Objects.AddCurve(
                curve,
                attributes
            )
        else:
            object_id = sc.doc.Objects.AddCurve(
                curve
            )
    except Exception:
        return None

    if (
        object_id is None or
        object_id == System.Guid.Empty
    ):
        return None

    return object_id


def clear_linesplan_source_output():
    """
    Dọn toàn bộ nguồn đường hình do MODEL112 quản lý rồi tạo lại bốn layer
    phẳng của V19:

        Station   - Sườn
        Waterline - Đường nước (DN)
        Buttock   - Đường cắt dọc (CD)
        HullLine  - Keel / Chine / Sheer / Transom

    Việc dọn cả cây layer cũ bảo đảm các sublayer STA/WL/CD và các layer con
    Keel/Chine/Sheer của các phiên bản trước không còn xuất hiện sau khi nâng cấp.
    """
    clear_sticky_objects(
        LINESPLAN_SOURCE_STICKY_KEY
    )

    try:
        layer_names = list(
            rs.LayerNames() or []
        )
    except Exception:
        layer_names = []

    prefix = (
        LINESPLAN_SOURCE_ROOT +
        u"::"
    )

    managed_layers = [
        name for name in layer_names
        if (
            TEXT_TYPE(name) == LINESPLAN_SOURCE_ROOT or
            TEXT_TYPE(name).startswith(prefix)
        )
    ]

    # Rhino không cho xóa current layer. Nếu người dùng đang đứng trong cây
    # SOURCE_3D, chuyển sang layer khung trước khi dọn layer legacy.
    try:
        current_layer = TEXT_TYPE(
            rs.CurrentLayer()
        )
        if (
            current_layer == LINESPLAN_SOURCE_ROOT or
            current_layer.startswith(prefix)
        ):
            ensure_model_layer_path(
                LAYER_KHUNG
            )
            rs.CurrentLayer(
                LAYER_KHUNG
            )
    except Exception:
        pass

    # Xóa hình học nguồn cũ kể cả khi sticky đã mất do đóng/mở lại Rhino.
    for layer_name in managed_layers:
        try:
            rs.LayerLocked(
                layer_name,
                False
            )
            rs.LayerVisible(
                layer_name,
                True
            )

            object_ids = rs.ObjectsByLayer(
                layer_name
            ) or []
            if object_ids:
                rs.DeleteObjects(
                    object_ids
                )
        except Exception:
            pass

    # Xóa layer con từ sâu lên nông, giữ lại SOURCE_3D làm layer gốc.
    managed_layers.sort(
        key=lambda name: TEXT_TYPE(name).count("::"),
        reverse=True
    )

    for layer_name in managed_layers:
        if TEXT_TYPE(layer_name) == LINESPLAN_SOURCE_ROOT:
            continue

        try:
            if rs.IsLayerEmpty(layer_name):
                rs.DeleteLayer(layer_name)
        except Exception:
            pass

    # Tạo trước đúng bốn layer cố định, kể cả khi một mặt phẳng cắt không có
    # giao tuyến để Layers panel vẫn luôn có cấu trúc nhất quán.
    for layer_name in (
        LINESPLAN_SOURCE_STATION,
        LINESPLAN_SOURCE_WATERLINE,
        LINESPLAN_SOURCE_BUTTOCK,
        LINESPLAN_SOURCE_HULLLINES
    ):
        ensure_nested_layer(
            layer_name
        )


def get_linesplan_intersection_tolerance(
    units_per_meter
):
    """
    Dung sai dùng để ghép giao tuyến của các panel.
    Giới hạn theo kích thước vật lý để tránh Document tolerance quá lớn.
    """
    try:
        document_tol = float(
            sc.doc.ModelAbsoluteTolerance
        )
    except Exception:
        document_tol = 0.0

    floor_tol = model_units_from_mm(
        0.02,
        units_per_meter
    )
    cap_tol = model_units_from_mm(
        0.50,
        units_per_meter
    )

    if document_tol <= 0.0:
        return floor_tol

    return max(
        floor_tol,
        min(
            document_tol,
            cap_tol
        )
    )


def intersect_hull_breps_with_plane(
    raw_breps,
    plane,
    tolerance
):
    """
    Cắt toàn bộ các Brep bằng một mặt phẳng và ghép các đoạn curve kề nhau.

    Ưu tiên Brep.CreateContourCurves vì Rhino/IronPython xử lý overload
    này ổn định hơn ở nhiều trường hợp. Nếu không có kết quả thì thử BrepPlane.
    """
    raw_curves = []

    for brep in raw_breps or []:
        if brep is None:
            continue

        curves = None

        try:
            curves = rg.Brep.CreateContourCurves(
                brep,
                plane
            )
        except Exception:
            curves = None

        if not curves:
            try:
                success, cut_curves, points = (
                    Rhino.Geometry.Intersect.Intersection.BrepPlane(
                        brep,
                        plane,
                        tolerance
                    )
                )

                if success:
                    curves = cut_curves
            except Exception:
                curves = None

        for curve in curves or []:
            if curve is not None:
                try:
                    if curve.GetLength() > tolerance:
                        raw_curves.append(
                            curve.DuplicateCurve()
                        )
                except Exception:
                    raw_curves.append(
                        curve.DuplicateCurve()
                    )

    if not raw_curves:
        return []

    # Ghép các đoạn nằm trên các panel kề nhau.
    try:
        joined = rg.Curve.JoinCurves(
            raw_curves,
            tolerance * 2.0
        )
    except Exception:
        joined = None

    if joined:
        return [
            curve.DuplicateCurve()
            for curve in joined
            if curve is not None
        ]

    return raw_curves


def evenly_spaced_values(
    minimum_value,
    maximum_value,
    count,
    include_ends=True
):
    count = int(count)

    if count <= 0:
        return []

    minimum_value = float(minimum_value)
    maximum_value = float(maximum_value)

    if count == 1:
        return [
            0.5 * (
                minimum_value +
                maximum_value
            )
        ]

    if include_ends:
        step = (
            maximum_value -
            minimum_value
        ) / float(count - 1)

        return [
            minimum_value +
            float(index) * step
            for index in range(count)
        ]

    # Chia count giá trị ở bên trong khoảng, tránh đúng biên hình học
    # vì ở baseline / H / Bmax/2 giao tuyến có thể suy biến thành điểm.
    step = (
        maximum_value -
        minimum_value
    ) / float(count + 1)

    return [
        minimum_value +
        float(index + 1) * step
        for index in range(count)
    ]


def custom_spaced_values(
    start_value,
    spacing_value,
    count,
    minimum_value,
    maximum_value,
    value_name
):
    """
    Sinh dãy:
        value_i = start + i * spacing

    Dùng cho Station / Waterline / CD khi người dùng bật Spacing tùy chỉnh.

    Không tự clip các đường ra ngoài phạm vi vì clip sẽ làm sai khoảng cách
    mà người dùng đã nhập. Nếu một vị trí vượt miền hình học, báo lỗi rõ.
    """
    count = int(
        count
    )

    start_value = float(
        start_value
    )
    spacing_value = float(
        spacing_value
    )
    minimum_value = float(
        minimum_value
    )
    maximum_value = float(
        maximum_value
    )

    if count <= 0:
        return []

    if spacing_value <= 0.0 and count > 1:
        raise Exception(
            u"Spacing của %s phải lớn hơn 0." %
            value_name
        )

    values = [
        start_value +
        float(index) * spacing_value
        for index in range(count)
    ]

    # Dung sai rất nhỏ chỉ để tránh lỗi số thực sát biên.
    domain_tolerance = max(
        1.0e-9,
        abs(
            maximum_value -
            minimum_value
        ) * 1.0e-10
    )

    outside = [
        value
        for value in values
        if (
            value <
            minimum_value -
            domain_tolerance
        ) or (
            value >
            maximum_value +
            domain_tolerance
        )
    ]

    if outside:
        raise Exception(
            (
                u"Vị trí %s vượt phạm vi hình học. "
                u"Giá trị cuối = %.3f, phạm vi cho phép %.3f → %.3f "
                u"(đơn vị mô hình). Hãy giảm số lượng, spacing hoặc đổi vị trí bắt đầu."
            ) %
            (
                value_name,
                values[-1],
                minimum_value,
                maximum_value
            )
        )

    # Kéo các giá trị cực sát biên về đúng biên để tránh số thực 24.0000000001.
    cleaned = []

    for value in values:
        if abs(
            value -
            minimum_value
        ) <= domain_tolerance:
            value = minimum_value

        if abs(
            value -
            maximum_value
        ) <= domain_tolerance:
            value = maximum_value

        cleaned.append(
            value
        )

    return cleaned




def keep_curves_starboard_half(
    curves,
    tolerance
):
    """
    Giữ phần Y >= 0 của các curve Station / Waterline.

    Curve hoàn toàn ở Starboard: giữ nguyên.
    Curve hoàn toàn ở Port: bỏ.
    Curve cắt Centerline: Split tại giao điểm với plane Y=0 và giữ segment Starboard.
    """
    result = []

    center_plane = rg.Plane(
        rg.Point3d.Origin,
        rg.Vector3d.YAxis
    )

    for curve in curves or []:
        if curve is None:
            continue

        try:
            bbox = curve.GetBoundingBox(
                True
            )
        except Exception:
            bbox = None

        if bbox is None:
            continue

        if bbox.Min.Y >= -tolerance:
            result.append(
                curve.DuplicateCurve()
            )
            continue

        if bbox.Max.Y < -tolerance:
            continue

        parameters = []

        try:
            events = (
                Rhino.Geometry.Intersect.Intersection.CurvePlane(
                    curve,
                    center_plane,
                    tolerance
                )
            )

            for event in events or []:
                try:
                    parameter = float(
                        event.ParameterA
                    )
                except Exception:
                    continue

                if (
                    parameter >
                    curve.Domain.T0 +
                    1.0e-10 and
                    parameter <
                    curve.Domain.T1 -
                    1.0e-10
                ):
                    parameters.append(
                        parameter
                    )
        except Exception:
            parameters = []

        if not parameters:
            # Nếu curve nằm gần centerline hoặc không thể split,
            # dùng điểm giữa để quyết định thay vì tự nhân đôi.
            try:
                mid_parameter = (
                    0.5 *
                    (
                        curve.Domain.T0 +
                        curve.Domain.T1
                    )
                )
                midpoint = curve.PointAt(
                    mid_parameter
                )

                if midpoint.Y >= -tolerance:
                    result.append(
                        curve.DuplicateCurve()
                    )
            except Exception:
                pass

            continue

        parameters = sorted(
            list(
                set(
                    [
                        round(
                            value,
                            12
                        )
                        for value in parameters
                    ]
                )
            )
        )

        try:
            segments = curve.Split(
                parameters
            )
        except Exception:
            segments = None

        for segment in segments or []:
            if segment is None:
                continue

            try:
                mid_parameter = (
                    0.5 *
                    (
                        segment.Domain.T0 +
                        segment.Domain.T1
                    )
                )
                midpoint = segment.PointAt(
                    mid_parameter
                )

                if midpoint.Y >= -tolerance:
                    result.append(
                        segment.DuplicateCurve()
                    )
            except Exception:
                pass

    return result


def copy_registered_hull_lines_to_linesplan_source(source_records=None):
    """
    Sao chép Keel / Chine / Sheer / Transom cùng lần dựng vỏ sang SOURCE_3D của Chế độ 2.
    Bản sao giúp Make2D độc lập với trạng thái Hide/Show của vỏ gốc.

    V19 gom toàn bộ các đường đặc trưng vào một layer HullLines duy nhất,
    không tạo layer con theo kind hoặc label.
    """
    use_sticky_source = source_records is None
    registered = (
        {"records": source_records}
        if source_records is not None
        else sc.sticky.get(FINAL_HULL_LINES_STICKY_KEY, {})
    )

    source_records = []
    all_copy_ids = []

    for record in registered.get(
        "records",
        []
    ):
        label = record.get(
            "label",
            "HullLine"
        )
        kind = record.get(
            "kind",
            "HullLine"
        )

        source_layer = LINESPLAN_SOURCE_HULLLINES

        original_to_copy = {}
        captured_geometries = dict(record.get("curve_geometries", []))

        for object_id in record.get(
            "all_ids",
            []
        ):
            geometry = captured_geometries.get(object_id)
            if geometry is None and use_sticky_source:
                try:
                    rhino_object = sc.doc.Objects.FindId(object_id)
                    geometry = rhino_object.Geometry if rhino_object else None
                except Exception:
                    geometry = None

            if not isinstance(
                geometry,
                rg.Curve
            ):
                continue

            copied_id = add_curve_to_named_layer(
                geometry.DuplicateCurve(),
                source_layer
            )

            if copied_id is not None:
                original_to_copy[
                    object_id
                ] = copied_id
                all_copy_ids.append(
                    copied_id
                )

        profile_ids = [
            original_to_copy[object_id]
            for object_id in record.get(
                "profile_ids",
                []
            )
            if object_id in original_to_copy
        ]

        plan_ids = [
            original_to_copy[object_id]
            for object_id in record.get(
                "plan_ids",
                []
            )
            if object_id in original_to_copy
        ]

        body_ids = [
            original_to_copy[object_id]
            for object_id in record.get(
                "body_ids",
                record.get("all_ids", [])
            )
            if object_id in original_to_copy
        ]

        copied_ids = list(
            original_to_copy.values()
        )

        if copied_ids:
            source_records.append(
                {
                    "label": label,
                    "kind": kind,
                    "profile_ids": profile_ids,
                    "plan_ids": plan_ids,
                    "body_ids": body_ids,
                    "all_ids": copied_ids,
                    "source_layer": source_layer
                }
            )

    return {
        "records": source_records,
        "all_ids": all_copy_ids
    }


def create_linesplan_source_curves(
    params,
    station_count,
    waterline_count,
    buttock_count,
    individual_layers=False,
    station_positions_model=None,
    waterline_positions_model=None,
    buttock_positions_model=None
):
    """
    Tạo ba họ giao tuyến và lưu metadata cho từng đường logic.

    Cây layer nguồn V19:
        MODEL112
        └── LINES_PLAN
            └── SOURCE_3D
                ├── Station
                ├── Waterline
                ├── Buttock
                └── HullLine

    Tham số individual_layers chỉ còn để tương thích code gọi cũ. V19 luôn
    gom đường theo bốn layer cố định và không tạo bất kỳ sublayer từng đường.
    """
    individual_layers = False

    clear_linesplan_source_output()

    sc.sticky[
        LINESPLAN_DATA_STICKY_KEY
    ] = {}

    source = create_hydrostatic_closed_hull(
        copy.deepcopy(params),
        include_hull_lines=True,
        respect_half_model=True
    )

    raw_breps = list(
        source.linesplan_breps
    )

    if not raw_breps:
        raise Exception(
            u"Không lấy được bề mặt vỏ để tạo đường hình."
        )

    units = float(
        params.units_per_meter
    )

    tolerance = (
        get_linesplan_intersection_tolerance(
            units
        )
    )

    L_local = float(
        params.length
    )
    B_local = float(
        params.beam
    )
    H_local = float(
        params.depth
    )
    z0 = float(
        params.baseline_z
    )

    station_count = int(
        station_count
    )
    waterline_count = int(
        waterline_count
    )
    buttock_count = int(
        buttock_count
    )

    # ------------------------------------------------------------
    # VỊ TRÍ CÁC ĐƯỜNG HÌNH
    #
    # Nếu Trang 4 truyền danh sách vị trí custom thì dùng đúng các giá trị đó.
    # Nếu không, V19 chia tự động với cả Station / Waterline / Buttock bắt đầu từ 0.
    # ------------------------------------------------------------
    if station_positions_model is None:
        station_x_values = evenly_spaced_values(
            0.0,
            L_local,
            station_count,
            True
        )
    else:
        station_x_values = list(
            station_positions_model
        )

    if waterline_positions_model is None:
        # V19: ĐN0 bắt đầu đúng tại đường cơ bản. Với N đường, bước tự động
        # là H/N để giữ đủ N đường nhưng không ép đường cuối đúng Z=H.
        if waterline_count > 0:
            waterline_step = (
                H_local /
                float(waterline_count)
            )
            waterline_z_values = [
                z0 +
                float(index) * waterline_step
                for index in range(waterline_count)
            ]
        else:
            waterline_z_values = []
    else:
        waterline_z_values = list(
            waterline_positions_model
        )

    if buttock_positions_model is None:
        # V19: CD0 bắt đầu đúng tại Centerline Y=0. Với N đường, bước tự động
        # là (Bmax/2)/N; đường cuối vì vậy vẫn nằm trong thân thay vì ở biên B/2.
        if buttock_count > 0:
            buttock_step = (
                (B_local * 0.5) /
                float(buttock_count)
            )
            buttock_y_values = [
                float(index) * buttock_step
                for index in range(buttock_count)
            ]
        else:
            buttock_y_values = []
    else:
        buttock_y_values = list(
            buttock_positions_model
        )

    station_ids = []
    waterline_ids = []
    buttock_ids = []

    station_records = []
    # Mỗi vị trí X phải có một hàng tọa độ, kể cả khi mặt cắt tại mũi
    # suy biến thành điểm và Rhino không thể tạo một Curve cho Station.
    station_slots = []
    waterline_records = []
    buttock_records = []

    # ------------------------------------------------------------
    # SƯỜN: X = const
    # ------------------------------------------------------------
    for station_index, x_value in enumerate(
        station_x_values
    ):
        label = linesplan_value_label(
            "STA",
            station_index,
            "X",
            x_value,
            units
        )

        layer_path = linesplan_child_layer(
            LINESPLAN_SOURCE_STATION,
            label,
            individual_layers
        )

        plane = rg.Plane(
            rg.Point3d(
                x_value,
                0.0,
                0.0
            ),
            rg.Vector3d.XAxis
        )

        curves = intersect_hull_breps_with_plane(
            raw_breps,
            plane,
            tolerance
        )

        if bool(
            getattr(
                params,
                "create_half_model",
                False
            )
        ):
            curves = keep_curves_starboard_half(
                curves,
                tolerance
            )

        record_ids = []

        for curve in curves:
            object_id = add_curve_to_named_layer(
                curve,
                layer_path
            )

            if object_id is not None:
                station_ids.append(
                    object_id
                )
                record_ids.append(
                    object_id
                )

        station_slot = {
            "station_index": int(station_index),
            "label": label,
            "value_model": float(x_value),
            "value_m": float(x_value) / units,
            "ids": list(record_ids),
            "source_layer": layer_path
        }
        station_slots.append(station_slot)
        if record_ids:
            station_records.append(station_slot)

    # ------------------------------------------------------------
    # ĐƯỜNG NƯỚC: Z = const
    # ------------------------------------------------------------
    for waterline_index, z_value in enumerate(
        waterline_z_values
    ):
        label = linesplan_value_label(
            "WL",
            waterline_index,
            "Z",
            z_value - z0,
            units
        )

        layer_path = linesplan_child_layer(
            LINESPLAN_SOURCE_WATERLINE,
            label,
            individual_layers
        )

        plane = rg.Plane(
            rg.Point3d(
                0.0,
                0.0,
                z_value
            ),
            rg.Vector3d.ZAxis
        )

        curves = intersect_hull_breps_with_plane(
            raw_breps,
            plane,
            tolerance
        )

        if bool(
            getattr(
                params,
                "create_half_model",
                False
            )
        ):
            curves = keep_curves_starboard_half(
                curves,
                tolerance
            )

        record_ids = []

        for curve in curves:
            object_id = add_curve_to_named_layer(
                curve,
                layer_path
            )

            if object_id is not None:
                waterline_ids.append(
                    object_id
                )
                record_ids.append(
                    object_id
                )

        if record_ids:
            waterline_records.append(
                {
                    "label": label,
                    "value_model": float(z_value),
                    "value_m": float(z_value - z0) / units,
                    "ids": list(record_ids),
                    "source_layer": layer_path
                }
            )

    # ------------------------------------------------------------
    # ĐƯỜNG CẮT DỌC: Y = const
    # ------------------------------------------------------------
    for buttock_index, y_value in enumerate(
        buttock_y_values
    ):
        label = linesplan_value_label(
            "CD",
            buttock_index,
            "Y",
            y_value,
            units
        )

        layer_path = linesplan_child_layer(
            LINESPLAN_SOURCE_BUTTOCK,
            label,
            individual_layers
        )

        plane = rg.Plane(
            rg.Point3d(
                0.0,
                y_value,
                0.0
            ),
            rg.Vector3d.YAxis
        )

        curves = intersect_hull_breps_with_plane(
            raw_breps,
            plane,
            tolerance
        )

        record_ids = []

        for curve in curves:
            object_id = add_curve_to_named_layer(
                curve,
                layer_path
            )

            if object_id is not None:
                buttock_ids.append(
                    object_id
                )
                record_ids.append(
                    object_id
                )

        if record_ids:
            buttock_records.append(
                {
                    "label": label,
                    "value_model": float(y_value),
                    "value_m": float(y_value) / units,
                    "ids": list(record_ids),
                    "source_layer": layer_path
                }
            )

    hull_line_source = (
        copy_registered_hull_lines_to_linesplan_source(
            source.hull_line_geometry_records
        )
    )

    hull_line_ids = list(
        hull_line_source.get(
            "all_ids",
            []
        )
    )

    all_ids = (
        station_ids +
        waterline_ids +
        buttock_ids +
        hull_line_ids
    )

    source_data = {
        "station_ids": list(station_ids),
        "waterline_ids": list(waterline_ids),
        "buttock_ids": list(buttock_ids),
        "all_ids": list(all_ids),
        "station_records": station_records,
        "station_slots": station_slots,
        "waterline_records": waterline_records,
        "buttock_records": buttock_records,
        "hull_line_records": hull_line_source.get(
            "records",
            []
        ),
        "hull_line_ids": hull_line_ids,
        "station_x_values": station_x_values,
        "waterline_z_values": waterline_z_values,
        "buttock_y_values": buttock_y_values,
        "parameter_signature": build_hull_parameter_signature(params),
        "half_model": bool(getattr(params, "create_half_model", False)),
        "individual_layers": bool(
            individual_layers
        )
    }

    sc.sticky[
        LINESPLAN_SOURCE_STICKY_KEY
    ] = list(
        all_ids
    )

    sc.sticky[
        LINESPLAN_DATA_STICKY_KEY
    ] = source_data

    sc.doc.Views.Redraw()

    return source_data


# =============================================================================
# MODULE 12C: BẢNG TỌA ĐỘ TỪ GIAO ĐIỂM STATION / WATERLINE / BUTTOCK
# =============================================================================
# Nguyên tắc V19:
# - ĐO TRỰC TIẾP trên khung SOURCE_3D, không lấy số liệu từ Make2D.
# - Hệ trục vật lý: X = chiều dài; Y = chiều rộng; Z = chiều cao.
# - NỬA CHIỀU RỘNG = abs(Y), tính từ mặt phẳng dọc tâm Y = 0.
# - CHIỀU CAO = Z - BaselineZ.
# - Mỗi hàng = một Station; cột ĐN lấy giao Station x Waterline;
#   cột CD lấy giao Station x Buttock.
# - Có thể bổ sung cột từ Keel / Chine / Sheer theo Y hoặc Z.
# - Có kiểm tra vật lý: |Y| không được vượt Bmax/2, Z không vượt H.
# - Không có giao Waterline/Buttock trên sườn có Curve -> ghi 0 theo
#   bảng truyền thống; sườn suy biến không có Curve -> để trống nếu
#   không đo được từ đường 3D khác, tránh coi thiếu giao là cao độ 0.
#   không có giao HullLine -> để trống, tránh nhầm với chiều rộng bằng 0.
# =============================================================================


def coordinate_curve_geometries(object_ids):
    result = []

    for object_id in object_ids or []:
        try:
            rhino_object = sc.doc.Objects.FindId(
                object_id
            )
        except Exception:
            rhino_object = None

        if rhino_object is None:
            continue

        geometry = rhino_object.Geometry

        if isinstance(
            geometry,
            rg.Curve
        ):
            result.append(
                geometry
            )

    return result


def coordinate_unique_points(points, tolerance):
    result = []

    for point in points or []:
        if point is None:
            continue

        is_duplicate = False

        for existing in result:
            try:
                if point.DistanceTo(existing) <= tolerance:
                    is_duplicate = True
                    break
            except Exception:
                pass

        if not is_duplicate:
            result.append(
                rg.Point3d(
                    float(point.X),
                    float(point.Y),
                    float(point.Z)
                )
            )

    return result


def coordinate_curve_set_intersections(
    ids_a,
    ids_b,
    tolerance
):
    """
    Giao HAI TẬP CURVE 3D và trả các Point3d duy nhất.

    V19 tuyệt đối không đo từ curve Make2D. Mọi giá trị bảng tọa độ được lấy
    từ chính các đường Station / Waterline / Buttock / HullLine trong SOURCE_3D.
    """
    curves_a = coordinate_curve_geometries(
        ids_a
    )
    curves_b = coordinate_curve_geometries(
        ids_b
    )

    points = []

    for curve_a in curves_a:
        for curve_b in curves_b:
            events = None

            try:
                events = (
                    Rhino.Geometry.Intersect.Intersection.CurveCurve(
                        curve_a,
                        curve_b,
                        tolerance,
                        tolerance
                    )
                )
            except Exception:
                events = None

            if events is None:
                continue

            try:
                event_count = events.Count
            except Exception:
                try:
                    event_count = len(events)
                except Exception:
                    event_count = 0

            for event_index in range(
                int(event_count)
            ):
                try:
                    event = events[event_index]
                except Exception:
                    continue

                try:
                    if event.IsPoint:
                        points.append(
                            event.PointA
                        )
                except Exception:
                    pass

    return coordinate_unique_points(
        points,
        tolerance * 2.0
    )


def coordinate_feature_at_station_plane(feature_ids, station_x, tolerance):
    """Đo đường keel/chine/sheer tại mặt phẳng sườn X = station_x.

    Mép của panel Loft có thể lệch rất nhỏ khỏi đường đặc trưng hiển thị;
    giao CurveCurve giữa hai đối tượng khi ấy có thể trả tập rỗng. Cột
    HullLine trong bảng tọa độ thuộc đường đặc trưng gốc, nên phải cắt
    chính đường ấy bằng mặt phẳng Station, không phụ thuộc mép Loft.
    """
    plane = rg.Plane(
        rg.Point3d(float(station_x), 0.0, 0.0),
        rg.Vector3d.XAxis
    )
    points = []
    plane_tolerance = max(float(tolerance) * 4.0, 1.0e-9)

    for curve in coordinate_curve_geometries(feature_ids):
        try:
            events = Rhino.Geometry.Intersect.Intersection.CurvePlane(
                curve, plane, tolerance
            )
        except Exception:
            events = None

        if events is not None:
            try:
                event_count = events.Count
            except Exception:
                try:
                    event_count = len(events)
                except Exception:
                    event_count = 0
            for event_index in range(int(event_count)):
                try:
                    event = events[event_index]
                    if event.IsPoint or event.IsOverlap:
                        points.append(event.PointA)
                    if event.IsOverlap:
                        points.append(event.PointA2)
                except Exception:
                    continue

        # Bổ sung hai đầu mút đúng trên mặt phẳng: Rhino có thể bỏ sự kiện
        # tiếp xúc ở đầu curve, nhất là Station tại transom/bow.
        for endpoint in (curve.PointAtStart, curve.PointAtEnd):
            if abs(float(endpoint.X) - float(station_x)) <= plane_tolerance:
                points.append(endpoint)

    return coordinate_filter_expected_planes(
        coordinate_unique_points(points, tolerance * 2.0),
        tolerance,
        expected_x=station_x
    )


def coordinate_filter_expected_planes(
    points,
    tolerance,
    expected_x=None,
    expected_y=None,
    expected_z=None
):
    """
    Lọc điểm giao theo đúng mặt phẳng hình học đã tạo.

    Station   : X = const
    Waterline : Z = const
    Buttock   : Y = const

    Việc lọc này ngăn một điểm giao sai đoạn/panel bị chọn chỉ vì nó có giá trị
    Y hoặc Z lớn hơn các điểm còn lại.
    """
    filtered = []

    plane_tolerance = max(
        float(tolerance) * 4.0,
        1.0e-9
    )

    for point in points or []:
        if point is None:
            continue

        if (
            expected_x is not None and
            abs(
                float(point.X) -
                float(expected_x)
            ) > plane_tolerance
        ):
            continue

        if (
            expected_y is not None and
            abs(
                float(point.Y) -
                float(expected_y)
            ) > plane_tolerance
        ):
            continue

        if (
            expected_z is not None and
            abs(
                float(point.Z) -
                float(expected_z)
            ) > plane_tolerance
        ):
            continue

        filtered.append(
            point
        )

    return filtered


def coordinate_starboard_point(points, tolerance):
    """
    Chọn điểm phía Starboard của mô hình Model 112 (+Y).

    Khi bảng dùng nửa chiều rộng, giá trị cuối cùng luôn là abs(Y), nhưng việc
    ưu tiên +Y giúp hai mạn đối xứng không tạo lựa chọn ngẫu nhiên.
    """
    if not points:
        return None

    starboard = [
        point
        for point in points
        if float(point.Y) >= -float(tolerance)
    ]

    candidates = (
        starboard
        if starboard
        else list(points)
    )

    return max(
        candidates,
        key=lambda point: float(point.Y)
    )


def coordinate_lowest_point(points):
    if not points:
        return None

    return min(
        points,
        key=lambda point: float(point.Z)
    )


def coordinate_output_value(
    value_model,
    units_per_meter,
    output_unit
):
    value_m = (
        float(value_model) /
        float(units_per_meter)
    )

    if TEXT_TYPE(output_unit).lower() == u"mm":
        return value_m * 1000.0

    return value_m


def coordinate_snap_zero(value, output_unit):
    # 0.005 mm hoặc 0.000005 m: tránh -0.00 do sai số giao tuyến.
    tolerance = (
        0.005
        if TEXT_TYPE(output_unit).lower() == u"mm"
        else 0.000005
    )

    if abs(float(value)) <= tolerance:
        return 0.0

    return float(value)


def coordinate_find_feature_record(
    source_data,
    feature_label
):
    for record in source_data.get(
        "hull_line_records",
        []
    ):
        if TEXT_TYPE(
            record.get(
                "label",
                ""
            )
        ) == TEXT_TYPE(feature_label):
            return record

    return None


def coordinate_validate_3d_point(
    point,
    params,
    tolerance,
    context_text=u"điểm đo"
):
    """
    Kiểm tra vật lý theo hệ trục 3D chuẩn của Model 112:

        X = chiều dài
        Y = chiều rộng; nửa chiều rộng = |Y|
        Z = chiều cao tuyệt đối trong model

    Chiều cao xuất bảng = Z - BaselineZ.
    """
    if point is None:
        return

    L_local = float(
        params.length
    )
    half_beam = float(
        params.beam
    ) * 0.5
    baseline_z = float(
        params.baseline_z
    )
    top_z = (
        baseline_z +
        float(params.depth)
    )

    bound_tolerance = max(
        float(tolerance) * 5.0,
        model_units_from_mm(
            1.0,
            params.units_per_meter
        )
    )

    x_value = float(point.X)
    y_value = float(point.Y)
    z_value = float(point.Z)

    if (
        x_value < -bound_tolerance or
        x_value > L_local + bound_tolerance
    ):
        raise Exception(
            u"%s có X=%.6f ngoài miền chiều dài [0, Lmax]." %
            (
                context_text,
                model_units_to_meters(
                    x_value,
                    params.units_per_meter
                )
            )
        )

    if abs(y_value) > half_beam + bound_tolerance:
        raise Exception(
            u"%s có nửa chiều rộng |Y|=%.6f m > Bmax/2=%.6f m. "
            u"Đã chặn kết quả để tránh xuất bảng sai phương đo." %
            (
                context_text,
                model_units_to_meters(
                    abs(y_value),
                    params.units_per_meter
                ),
                model_units_to_meters(
                    half_beam,
                    params.units_per_meter
                )
            )
        )

    # V19: KHÔNG đặt giới hạn dưới theo Z.
    # Một số hình dạng vỏ có thể võng/lõm nhẹ xuống dưới Baseline,
    # vì vậy Z - BaselineZ được phép âm và được giữ nguyên trong bảng tọa độ.
    # Chỉ giữ giới hạn trên theo H để bắt các điểm đo thực sự vượt miền thân tàu.
    if z_value > top_z + bound_tolerance:
        raise Exception(
            u"%s có Z=%.6f m vượt giới hạn chiều cao H=%.6f m." %
            (
                context_text,
                model_units_to_meters(
                    z_value - baseline_z,
                    params.units_per_meter
                ),
                model_units_to_meters(
                    float(params.depth),
                    params.units_per_meter
                )
            )
        )


def coordinate_half_breadth_model(
    point,
    params,
    tolerance,
    context_text
):
    coordinate_validate_3d_point(
        point,
        params,
        tolerance,
        context_text
    )

    value = abs(
        float(point.Y)
    )

    half_beam = float(
        params.beam
    ) * 0.5

    if value > half_beam:
        # Chỉ snap phần vượt cực nhỏ do tolerance về đúng B/2.
        value = half_beam

    return value


def coordinate_height_model(
    point,
    params,
    tolerance,
    context_text
):
    coordinate_validate_3d_point(
        point,
        params,
        tolerance,
        context_text
    )

    value = (
        float(point.Z) -
        float(params.baseline_z)
    )

    # V19: giữ nguyên giá trị âm. Không snap về 0, vì điểm vỏ nằm dưới
    # Baseline là dữ liệu hình học hợp lệ chứ không nhất thiết là sai số số học.
    return value


def build_linesplan_coordinate_table(
    params,
    source_data,
    extra_columns=None,
    output_unit=u"mm"
):
    """
    MODEL 112 V19 - BẢNG TỌA ĐỘ ĐO TRỰC TIẾP TỪ KHUNG 3D.

    Hệ trục duy nhất dùng để đo:
        X = chiều dài tàu;
        Y = chiều rộng, nửa chiều rộng = abs(Y) tính từ Centerline Y=0;
        Z = chiều cao, bảng ghi Z - BaselineZ.

    Cột nền:
        - Station x Waterline -> lấy abs(Y) của giao điểm 3D;
        - Station x Buttock   -> lấy Z - BaselineZ của giao điểm 3D.

    Không dùng tọa độ Make2D, không dùng bounding box bản vẽ 2D và KHÔNG trừ
    vị trí Waterline/Buttock đầu tiên. Vì vậy việc dời/arrange hình chiếu 2D
    không thể làm thay đổi bảng tọa độ.
    """
    if not source_data:
        raise Exception(
            u"Chưa có dữ liệu đường cắt 3D."
        )

    station_records = list(source_data.get("station_records", []))
    # station_records chỉ chứa Curve để Make2D xử lý. Bảng tọa độ cần
    # đủ mọi mặt phẳng X, bao gồm tiết diện mũi suy biến thành một điểm.
    station_slots = list(
        source_data.get("station_slots", station_records)
    )
    waterline_records = list(
        source_data.get(
            "waterline_records",
            []
        )
    )
    buttock_records = list(
        source_data.get(
            "buttock_records",
            []
        )
    )

    if not station_slots:
        raise Exception(
            u"Không có Station để tạo bảng tọa độ."
        )

    if not waterline_records:
        raise Exception(
            u"Không có Waterline để tạo nhóm Nửa chiều rộng."
        )

    if not buttock_records:
        raise Exception(
            u"Không có Buttock/CD để tạo nhóm Chiều cao."
        )

    units = float(
        params.units_per_meter
    )

    tolerance = max(
        get_linesplan_intersection_tolerance(
            units
        ) * 2.0,
        model_units_from_mm(
            0.10,
            units
        )
    )

    # Gốc đo vật lý của mô hình 3D, KHÔNG lấy theo đường số 0.
    x_origin = 0.0
    y_origin = 0.0
    z_origin = float(
        params.baseline_z
    )

    extra_columns = list(
        extra_columns or []
    )

    width_extras = [
        item
        for item in extra_columns
        if TEXT_TYPE(
            item.get(
                "axis",
                "Y"
            )
        ).upper() == "Y"
    ]

    height_extras = [
        item
        for item in extra_columns
        if TEXT_TYPE(
            item.get(
                "axis",
                "Z"
            )
        ).upper() == "Z"
    ]

    missing_features = []

    for item in extra_columns:
        feature_label = item.get(
            "feature_label",
            ""
        )

        if coordinate_find_feature_record(
            source_data,
            feature_label
        ) is None:
            missing_features.append(
                TEXT_TYPE(feature_label)
            )

    if missing_features:
        raise Exception(
            u"Các đường bổ sung không tồn tại trong mô hình hiện tại: %s" %
            u", ".join(
                missing_features
            )
        )

    width_columns = []

    for index, record in enumerate(
        waterline_records
    ):
        width_columns.append(
            {
                "name": u"ĐN%d" % int(index),
                "kind": "waterline",
                "record": record
            }
        )

    for item in width_extras:
        width_columns.append(
            {
                "name": TEXT_TYPE(
                    item.get(
                        "name",
                        item.get(
                            "feature_label",
                            u"Bổ sung"
                        )
                    )
                ),
                "kind": "feature",
                "feature_label": TEXT_TYPE(
                    item.get(
                        "feature_label",
                        ""
                    )
                ),
                "axis": "Y"
            }
        )

    height_columns = []

    for index, record in enumerate(
        buttock_records
    ):
        height_columns.append(
            {
                "name": u"CD%d" % int(index),
                "kind": "buttock",
                "record": record
            }
        )

    for item in height_extras:
        height_columns.append(
            {
                "name": TEXT_TYPE(
                    item.get(
                        "name",
                        item.get(
                            "feature_label",
                            u"Bổ sung"
                        )
                    )
                ),
                "kind": "feature",
                "feature_label": TEXT_TYPE(
                    item.get(
                        "feature_label",
                        ""
                    )
                ),
                "axis": "Z"
            }
        )

    rows = []
    maximum_measured_half_breadth = 0.0
    maximum_measured_height = 0.0
    keel_record = coordinate_find_feature_record(source_data, "Keel")
    keel_ids = (
        keel_record.get("all_ids", [])
        if keel_record is not None else []
    )

    for station_ordinal, station_record in enumerate(
        station_slots
    ):
        station_index = int(
            station_record.get("station_index", station_ordinal)
        )
        station_ids = station_record.get(
            "ids",
            []
        )
        station_x = float(
            station_record.get(
                "value_model",
                0.0
            )
        )

        width_values = []

        for column in width_columns:
            if column.get(
                "kind"
            ) == "waterline":
                waterline_record = column[
                    "record"
                ]
                other_ids = waterline_record.get(
                    "ids",
                    []
                )

                points = coordinate_curve_set_intersections(
                    station_ids,
                    other_ids,
                    tolerance
                )

                if not station_ids:
                    # Giao theo X trực tiếp trên đường nước, vì mặt cắt
                    # suy biến không có Curve để cắt CurveCurve.
                    points = coordinate_feature_at_station_plane(
                        other_ids, station_x, tolerance
                    )

                points = coordinate_filter_expected_planes(
                    points,
                    tolerance,
                    expected_x=station_x,
                    expected_z=float(
                        waterline_record.get(
                            "value_model",
                            0.0
                        )
                    )
                )

                point = coordinate_starboard_point(
                    points,
                    tolerance
                )

                context_text = (
                    u"STA%d × ĐN" %
                    int(station_index)
                )
            else:
                feature_record = (
                    coordinate_find_feature_record(
                        source_data,
                        column.get(
                            "feature_label",
                            ""
                        )
                    )
                )

                other_ids = (
                    feature_record.get(
                        "all_ids",
                        []
                    )
                    if feature_record is not None
                    else []
                )

                points = coordinate_feature_at_station_plane(
                    other_ids,
                    station_x,
                    tolerance
                )

                point = coordinate_starboard_point(
                    points,
                    tolerance
                )

                context_text = (
                    u"STA%d × %s" %
                    (
                        int(station_index),
                        TEXT_TYPE(
                            column.get(
                                "feature_label",
                                u"HullLine"
                            )
                        )
                    )
                )

            if point is None:
                output_value = (
                    None if not station_ids or column.get("kind") == "feature"
                    else 0.0
                )
            else:
                half_breadth_model = (
                    coordinate_half_breadth_model(
                        point,
                        params,
                        tolerance,
                        context_text
                    )
                )

                maximum_measured_half_breadth = max(
                    maximum_measured_half_breadth,
                    half_breadth_model
                )

                output_value = coordinate_output_value(
                    half_breadth_model,
                    units,
                    output_unit
                )

            width_values.append(
                coordinate_snap_zero(output_value, output_unit)
                if output_value is not None else None
            )

        height_values = []

        for column in height_columns:
            if column.get(
                "kind"
            ) == "buttock":
                buttock_record = column[
                    "record"
                ]
                other_ids = buttock_record.get(
                    "ids",
                    []
                )

                points = coordinate_curve_set_intersections(
                    station_ids,
                    other_ids,
                    tolerance
                )

                if not station_ids:
                    points = coordinate_feature_at_station_plane(
                        other_ids, station_x, tolerance
                    )

                points = coordinate_filter_expected_planes(
                    points,
                    tolerance,
                    expected_x=station_x,
                    expected_y=float(
                        buttock_record.get(
                            "value_model",
                            0.0
                        )
                    )
                )

                # CD0 tại đỉnh mũi có thể không cho giao với vỏ
                # (mặt cắt chỉ là điểm). Đọc Z từ keel/stem 3D.
                if (
                    not points and not station_ids and keel_ids and
                    abs(float(buttock_record.get("value_model", 0.0)))
                    <= tolerance * 4.0
                ):
                    points = coordinate_filter_expected_planes(
                        coordinate_feature_at_station_plane(
                            keel_ids, station_x, tolerance
                        ),
                        tolerance,
                        expected_x=station_x,
                        expected_y=0.0
                    )

                point = coordinate_lowest_point(
                    points
                )

                context_text = (
                    u"STA%d × CD" %
                    int(station_index)
                )
            else:
                feature_record = (
                    coordinate_find_feature_record(
                        source_data,
                        column.get(
                            "feature_label",
                            ""
                        )
                    )
                )

                other_ids = (
                    feature_record.get(
                        "all_ids",
                        []
                    )
                    if feature_record is not None
                    else []
                )

                points = coordinate_feature_at_station_plane(
                    other_ids,
                    station_x,
                    tolerance
                )

                # HullLine có thể có Port + Starboard. Chọn mạn phải rồi đọc Z.
                point = coordinate_starboard_point(
                    points,
                    tolerance
                )

                context_text = (
                    u"STA%d × %s" %
                    (
                        int(station_index),
                        TEXT_TYPE(
                            column.get(
                                "feature_label",
                                u"HullLine"
                            )
                        )
                    )
                )

            if point is None:
                output_value = (
                    None if not station_ids or column.get("kind") == "feature"
                    else 0.0
                )
            else:
                height_model = coordinate_height_model(
                    point,
                    params,
                    tolerance,
                    context_text
                )

                maximum_measured_height = max(
                    maximum_measured_height,
                    height_model
                )

                output_value = coordinate_output_value(
                    height_model,
                    units,
                    output_unit
                )

            height_values.append(
                coordinate_snap_zero(output_value, output_unit)
                if output_value is not None else None
            )

        rows.append(
            {
                "station_index": int(
                    station_index
                ),
                "station_label": TEXT_TYPE(
                    station_index
                ),
                "station_x_model": station_x,
                "station_x_relative": station_x,
                "station_x_m": station_x / units,
                "station_x_output": coordinate_output_value(
                    station_x,
                    units,
                    output_unit
                ),
                "width_values": width_values,
                "height_values": height_values
            }
        )

    return {
        "title": u"BẢNG TỌA ĐỘ",
        "unit": TEXT_TYPE(output_unit),
        "measurement_source": u"SOURCE_3D",
        "measurement_rule": u"X=chiều dài; nửa rộng=|Y| từ Y=0; chiều cao=Z-BaselineZ (được phép âm)",
        "x_origin_model": x_origin,
        "y_origin_model": y_origin,
        "z_origin_model": z_origin,
        "x_origin_output": 0.0,
        "y_origin_output": 0.0,
        "z_origin_output": coordinate_output_value(
            z_origin,
            units,
            output_unit
        ),
        "max_half_beam_output": coordinate_output_value(
            float(params.beam) * 0.5,
            units,
            output_unit
        ),
        "max_height_output": coordinate_output_value(
            float(params.depth),
            units,
            output_unit
        ),
        "max_measured_half_breadth_output": coordinate_output_value(
            maximum_measured_half_breadth,
            units,
            output_unit
        ),
        "max_measured_height_output": coordinate_output_value(
            maximum_measured_height,
            units,
            output_unit
        ),
        "width_columns": width_columns,
        "height_columns": height_columns,
        "rows": rows,
        "station_count": len(station_slots),
        "station_curve_count": len(station_records),
        "station_missing_indices": [
            int(slot.get("station_index", index))
            for index, slot in enumerate(station_slots)
            if not slot.get("ids")
        ],
        "waterline_count": len(
            waterline_records
        ),
        "buttock_count": len(
            buttock_records
        ),
        "extra_columns": extra_columns
    }


def model112_table_column_widths(headers, rows, minimum=7):
    """Độ rộng từng cột tính từ dữ liệu và nhãn, dùng cùng cho mọi dòng."""
    widths = [max(int(minimum), len(TEXT_TYPE(h))) for h in headers]
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("Số cột hiển thị không khớp tiêu đề bảng.")
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(TEXT_TYPE(value)))
    return widths


def model112_table_text_row(cells, widths, header=False, left_indices=None):
    left_indices = set(left_indices or [])
    formatted = []
    for index, (value, width) in enumerate(zip(cells, widths)):
        content = TEXT_TYPE(value)
        if header:
            formatted.append(content.center(width))
        elif index in left_indices:
            formatted.append(content.ljust(width))
        else:
            formatted.append(content.rjust(width))
    return u" | ".join(formatted)


def model112_table_separator(widths):
    return u"-+-".join(u"-" * width for width in widths)


def model112_set_table_font(control):
    """Bảng văn bản phải dùng chữ có độ rộng cố định ở Rhino/Eto."""
    for family in ("Consolas", "Courier New"):
        try:
            control.Font = drawing.Font(family, 10)
            return
        except Exception:
            continue


def format_linesplan_coordinate_table(table_data):
    if not table_data:
        return u"Chưa có bảng tọa độ."

    width_names = [
        TEXT_TYPE(
            item.get(
                "name",
                ""
            )
        )
        for item in table_data.get(
            "width_columns",
            []
        )
    ]

    height_names = [
        TEXT_TYPE(
            item.get(
                "name",
                ""
            )
        )
        for item in table_data.get(
            "height_columns",
            []
        )
    ]

    unit = TEXT_TYPE(
        table_data.get(
            "unit",
            u"mm"
        )
    )

    decimals = (
        2
        if unit.lower() == u"mm"
        else 3
    )

    headers = [u"SƯỜN", u"X (m)"] + width_names + height_names
    number_format = u"%%.%df" % int(decimals)
    display_rows = []
    for row in table_data.get("rows", []):
        x_m = row.get("station_x_m", None)
        values = [
            TEXT_TYPE(row.get("station_label", "")),
            u"%.3f" % float(x_m) if x_m is not None else u"—"
        ]
        for value in row.get("width_values", []) + row.get("height_values", []):
            if value is None:
                values.append(u"—")
            else:
                formatted = number_format % float(value)
                if formatted.startswith(u"-0") and float(formatted) == 0.0:
                    formatted = number_format % 0.0
                values.append(formatted)
        display_rows.append(values)

    widths = model112_table_column_widths(headers, display_rows, minimum=8)
    width_start = 2
    width_span = sum(widths[width_start:width_start + len(width_names)]) + 3 * max(0, len(width_names) - 1)
    height_start = width_start + len(width_names)
    height_span = sum(widths[height_start:]) + 3 * max(0, len(height_names) - 1)
    if width_names and width_span < len(u"NỬA CHIỀU RỘNG"):
        widths[width_start] += len(u"NỬA CHIỀU RỘNG") - width_span
        width_span = len(u"NỬA CHIỀU RỘNG")
    if height_names and height_span < len(u"CHIỀU CAO"):
        widths[height_start] += len(u"CHIỀU CAO") - height_span
        height_span = len(u"CHIỀU CAO")

    lines = []
    lines.append(
        u"BẢNG TỌA ĐỘ | Đơn vị: %s" %
        unit
    )
    lines.append(
        u"Nguồn đo: KHUNG 3D | X = chiều dài | Nửa rộng = |Y| từ Centerline | Cao = Z - Baseline (được phép âm)"
    )
    lines.append(
        u"Kiểm tra: nửa rộng lớn nhất đo được %.3f %s / giới hạn Bmax/2 %.3f %s | "
        u"cao lớn nhất đo được %.3f %s / giới hạn H %.3f %s" %
        (
            float(
                table_data.get(
                    "max_measured_half_breadth_output",
                    0.0
                )
            ),
            unit,
            float(
                table_data.get(
                    "max_half_beam_output",
                    0.0
                )
            ),
            unit,
            float(
                table_data.get(
                    "max_measured_height_output",
                    0.0
                )
            ),
            unit,
            float(
                table_data.get(
                    "max_height_output",
                    0.0
                )
            ),
            unit
        )
    )

    lines.append(
        u" " * (sum(widths[:width_start]) + 3 * width_start) +
        u"NỬA CHIỀU RỘNG".center(width_span) +
        u" | " +
        u"CHIỀU CAO".center(height_span)
    )
    lines.append(model112_table_text_row(headers, widths, header=True))
    lines.append(model112_table_separator(widths))

    for values in display_rows:
        lines.append(model112_table_text_row(values, widths))

    return u"\n".join(
        lines
    )


def xlsx_xml_escape(value):
    text_value = TEXT_TYPE(
        value
    )

    return (
        text_value.replace(
            u"&",
            u"&amp;"
        ).replace(
            u"<",
            u"&lt;"
        ).replace(
            u">",
            u"&gt;"
        ).replace(
            u'"',
            u"&quot;"
        ).replace(
            u"'",
            u"&apos;"
        )
    )


def xlsx_column_letter(index_zero_based):
    number = int(
        index_zero_based
    ) + 1
    letters = u""

    while number > 0:
        number, remainder = divmod(
            number - 1,
            26
        )
        letters = chr(
            65 + remainder
        ) + letters

    return letters


def xlsx_inline_cell_xml(
    row_index,
    column_index,
    value,
    style_index
):
    cell_ref = (
        xlsx_column_letter(
            column_index
        ) +
        TEXT_TYPE(
            row_index
        )
    )

    return (
        u'<c r="%s" s="%d" t="inlineStr">'
        u'<is><t xml:space="preserve">%s</t></is></c>'
    ) % (
        cell_ref,
        int(style_index),
        xlsx_xml_escape(
            value
        )
    )


def xlsx_number_cell_xml(
    row_index,
    column_index,
    value,
    style_index
):
    cell_ref = (
        xlsx_column_letter(
            column_index
        ) +
        TEXT_TYPE(
            row_index
        )
    )

    return (
        u'<c r="%s" s="%d"><v>%.12g</v></c>'
    ) % (
        cell_ref,
        int(style_index),
        float(value)
    )


def xlsx_empty_cell_xml(row_index, column_index, style_index):
    cell_ref = xlsx_column_letter(column_index) + TEXT_TYPE(row_index)
    return u'<c r="%s" s="%d"/>' % (cell_ref, int(style_index))


def write_linesplan_coordinate_xlsx(
    file_path,
    table_data
):
    """
    Ghi .xlsx trực tiếp bằng Open XML, không phụ thuộc Excel COM/openpyxl.
    Vì vậy máy chạy Rhino chỉ cần thư viện chuẩn zipfile của IronPython.
    """
    if not table_data:
        raise Exception(
            u"Chưa có bảng tọa độ để xuất Excel."
        )

    width_columns = list(
        table_data.get(
            "width_columns",
            []
        )
    )
    height_columns = list(
        table_data.get(
            "height_columns",
            []
        )
    )
    rows = list(
        table_data.get(
            "rows",
            []
        )
    )

    total_columns = (
        2 +
        len(width_columns) +
        len(height_columns)
    )

    if total_columns < 2:
        raise Exception(
            u"Bảng tọa độ không có đủ cột để xuất."
        )

    last_column = xlsx_column_letter(
        total_columns - 1
    )
    width_start_col = 2
    width_end_col = (
        width_start_col +
        len(width_columns) - 1
    )
    height_start_col = (
        width_end_col + 1
    )
    height_end_col = (
        total_columns - 1
    )

    sheet_rows = []

    # Row 1 - title.
    sheet_rows.append(
        u'<row r="1" ht="24" customHeight="1">%s</row>' %
        xlsx_inline_cell_xml(
            1,
            0,
            u"BẢNG TỌA ĐỘ",
            1
        )
    )

    # Row 2 - group headers.
    row2_cells = [
        xlsx_inline_cell_xml(
            2,
            0,
            u"SƯỜN",
            2
        ),
        xlsx_inline_cell_xml(
            2,
            1,
            u"X (m)",
            2
        )
    ]

    if width_columns:
        row2_cells.append(
            xlsx_inline_cell_xml(
                2,
                width_start_col,
                u"NỬA CHIỀU RỘNG",
                2
            )
        )

    if height_columns:
        row2_cells.append(
            xlsx_inline_cell_xml(
                2,
                height_start_col,
                u"CHIỀU CAO",
                2
            )
        )

    sheet_rows.append(
        u'<row r="2" ht="22" customHeight="1">%s</row>' %
        u"".join(
            row2_cells
        )
    )

    # Row 3 - individual headers.
    row3_cells = []

    for column_index, column in enumerate(
        width_columns,
        width_start_col
    ):
        row3_cells.append(
            xlsx_inline_cell_xml(
                3,
                column_index,
                column.get(
                    "name",
                    ""
                ),
                3
            )
        )

    for offset, column in enumerate(
        height_columns
    ):
        row3_cells.append(
            xlsx_inline_cell_xml(
                3,
                height_start_col + offset,
                column.get(
                    "name",
                    ""
                ),
                3
            )
        )

    sheet_rows.append(
        u'<row r="3" ht="22" customHeight="1">%s</row>' %
        u"".join(
            row3_cells
        )
    )

    numeric_style = (
        5
        if TEXT_TYPE(
            table_data.get(
                "unit",
                u"mm"
            )
        ).lower() == u"mm"
        else 6
    )

    for row_offset, data_row in enumerate(
        rows
    ):
        excel_row = 4 + row_offset
        cells = [
            xlsx_inline_cell_xml(
                excel_row,
                0,
                data_row.get(
                    "station_label",
                    ""
                ),
                4
            ),
            xlsx_number_cell_xml(
                excel_row,
                1,
                data_row.get("station_x_m", 0.0),
                6
            )
        ]

        column_index = width_start_col

        for value in data_row.get(
            "width_values",
            []
        ):
            cells.append(
                xlsx_empty_cell_xml(excel_row, column_index, numeric_style)
                if value is None else
                xlsx_number_cell_xml(
                    excel_row, column_index, value, numeric_style
                )
            )
            column_index += 1

        for value in data_row.get(
            "height_values",
            []
        ):
            cells.append(
                xlsx_empty_cell_xml(excel_row, column_index, numeric_style)
                if value is None else
                xlsx_number_cell_xml(
                    excel_row, column_index, value, numeric_style
                )
            )
            column_index += 1

        sheet_rows.append(
            u'<row r="%d">%s</row>' %
            (
                excel_row,
                u"".join(
                    cells
                )
            )
        )

    note_row = 5 + len(rows)
    unit = TEXT_TYPE(
        table_data.get(
            "unit",
            u"mm"
        )
    )
    note_text = (
        u"Đơn vị: %s | Nguồn đo: SOURCE_3D | X=chiều dài | "
        u"Nửa rộng=|Y| từ Centerline Y=0 | Chiều cao=Z-BaselineZ, cho phép âm | "
        u"Max nửa rộng đo=%.3f / Bmax/2=%.3f | Max cao đo=%.3f / H=%.3f"
    ) % (
        unit,
        float(
            table_data.get(
                "max_measured_half_breadth_output",
                0.0
            )
        ),
        float(
            table_data.get(
                "max_half_beam_output",
                0.0
            )
        ),
        float(
            table_data.get(
                "max_measured_height_output",
                0.0
            )
        ),
        float(
            table_data.get(
                "max_height_output",
                0.0
            )
        )
    )

    sheet_rows.append(
        u'<row r="%d" ht="30" customHeight="1">%s</row>' %
        (
            note_row,
            xlsx_inline_cell_xml(
                note_row,
                0,
                note_text,
                7
            )
        )
    )

    merge_cells = [
        u'A1:%s1' % last_column,
        u'A2:A3',
        u'B2:B3'
    ]

    if width_columns:
        merge_cells.append(
            u'%s2:%s2' %
            (
                xlsx_column_letter(
                    width_start_col
                ),
                xlsx_column_letter(
                    width_end_col
                )
            )
        )

    if height_columns:
        merge_cells.append(
            u'%s2:%s2' %
            (
                xlsx_column_letter(
                    height_start_col
                ),
                xlsx_column_letter(
                    height_end_col
                )
            )
        )

    merge_cells.append(
        u'A%d:%s%d' %
        (
            note_row,
            last_column,
            note_row
        )
    )

    merge_xml = (
        u'<mergeCells count="%d">%s</mergeCells>' %
        (
            len(merge_cells),
            u"".join(
                [
                    u'<mergeCell ref="%s"/>' %
                    item
                    for item in merge_cells
                ]
            )
        )
    )

    col_xml = [
        u'<col min="1" max="1" width="10" customWidth="1"/>',
        u'<col min="2" max="2" width="12" customWidth="1"/>'
    ]

    if total_columns > 2:
        col_xml.append(
            u'<col min="3" max="%d" width="13" customWidth="1"/>' %
            total_columns
        )

    sheet_xml = (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        u'<dimension ref="A1:%s%d"/>'
        u'<sheetViews><sheetView workbookViewId="0">'
        u'<pane xSplit="2" ySplit="3" topLeftCell="C4" activePane="bottomRight" state="frozen"/>'
        u'</sheetView></sheetViews>'
        u'<sheetFormatPr defaultRowHeight="18"/>'
        u'<cols>%s</cols>'
        u'<sheetData>%s</sheetData>'
        u'%s'
        u'<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        u'<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        u'</worksheet>'
    ) % (
        last_column,
        note_row,
        u"".join(
            col_xml
        ),
        u"".join(
            sheet_rows
        ),
        merge_xml
    )

    styles_xml = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="0.000"/></numFmts>
  <fonts count="3">
    <font><sz val="12"/><name val="Times New Roman"/></font>
    <font><b/><sz val="14"/><name val="Times New Roman"/></font>
    <font><b/><sz val="12"/><name val="Times New Roman"/></font>
  </fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color auto="1"/></left><right style="thin"><color auto="1"/></right><top style="thin"><color auto="1"/></top><bottom style="thin"><color auto="1"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="8">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="2" fontId="2" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="164" fontId="2" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

    workbook_xml = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="BANG TOA DO" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

    workbook_rels_xml = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    rels_xml = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    content_types_xml = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    output_directory = os.path.dirname(
        file_path
    )

    if output_directory and not os.path.isdir(
        output_directory
    ):
        os.makedirs(
            output_directory
        )

    archive = zipfile.ZipFile(
        file_path,
        "w",
        zipfile.ZIP_DEFLATED
    )

    try:
        archive.writestr(
            "[Content_Types].xml",
            content_types_xml.encode(
                "utf-8"
            )
        )
        archive.writestr(
            "_rels/.rels",
            rels_xml.encode(
                "utf-8"
            )
        )
        archive.writestr(
            "xl/workbook.xml",
            workbook_xml.encode(
                "utf-8"
            )
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            workbook_rels_xml.encode(
                "utf-8"
            )
        )
        archive.writestr(
            "xl/styles.xml",
            styles_xml.encode(
                "utf-8"
            )
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            sheet_xml.encode(
                "utf-8"
            )
        )
    finally:
        archive.close()

    return file_path


def build_coordinate_xlsx_filename(table_data):
    timestamp = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    return (
        "Model112_Bang_toa_do_%dSTA_%dWL_%dCD_%s.xlsx" %
        (
            int(
                table_data.get(
                    "station_count",
                    0
                )
            ),
            int(
                table_data.get(
                    "waterline_count",
                    0
                )
            ),
            int(
                table_data.get(
                    "buttock_count",
                    0
                )
            ),
            timestamp
        )
    )


def all_document_object_ids():
    try:
        return set(
            rs.AllObjects(
                select=False,
                include_lights=False,
                include_grips=False
            ) or []
        )
    except Exception:
        result = set()

        try:
            for rhino_object in sc.doc.Objects:
                if rhino_object is not None:
                    result.add(
                        rhino_object.Id
                    )
        except Exception:
            pass

        return result


def set_objects_layer(
    object_ids,
    layer_name
):
    if not object_ids:
        return

    attributes_template = get_linesplan_layer_attributes(
        layer_name
    )

    if attributes_template is None:
        return

    target_layer_index = (
        attributes_template.LayerIndex
    )

    for object_id in object_ids:
        try:
            rhino_object = sc.doc.Objects.FindId(
                object_id
            )

            if rhino_object is None:
                continue

            attributes = (
                rhino_object.Attributes.Duplicate()
            )
            attributes.LayerIndex = (
                target_layer_index
            )

            sc.doc.Objects.ModifyAttributes(
                rhino_object,
                attributes,
                True
            )
        except Exception:
            pass


def move_objects_to_anchor(
    object_ids,
    anchor_x,
    anchor_y
):
    """
    Đưa góc trái-dưới của bounding box nhóm 2D tới anchor trên World XY.
    """
    if not object_ids:
        return

    try:
        bbox_points = rs.BoundingBox(
            object_ids
        )
    except Exception:
        bbox_points = None

    if not bbox_points:
        return

    minimum_x = min(
        point.X
        for point in bbox_points
    )
    minimum_y = min(
        point.Y
        for point in bbox_points
    )

    translation = rg.Transform.Translation(
        float(anchor_x) - minimum_x,
        float(anchor_y) - minimum_y,
        0.0
    )

    transform_object_ids(
        object_ids,
        translation
    )



def get_objects_bbox_xy(object_ids):
    """Trả (min_x, min_y, max_x, max_y) của một nhóm object 2D."""
    if not object_ids:
        return None

    try:
        bbox_points = rs.BoundingBox(
            object_ids
        )
    except Exception:
        bbox_points = None

    if not bbox_points:
        return None

    return (
        min(point.X for point in bbox_points),
        min(point.Y for point in bbox_points),
        max(point.X for point in bbox_points),
        max(point.Y for point in bbox_points)
    )


def objects_bbox_size_xy(object_ids):
    bbox = get_objects_bbox_xy(
        object_ids
    )

    if bbox is None:
        return 0.0, 0.0

    return (
        max(0.0, bbox[2] - bbox[0]),
        max(0.0, bbox[3] - bbox[1])
    )


def collect_record_object_ids(records, key="ids"):
    """Gom ID của nhiều record thành một danh sách duy nhất, không lặp."""
    result = []
    seen = set()

    for record in records or []:
        for object_id in record.get(key, []) or []:
            if object_id in seen:
                continue
            seen.add(object_id)
            result.append(object_id)

    return result


def collect_hull_feature_projection_ids(records, projection_key):
    result = []
    seen = set()

    for record in records or []:
        for object_id in record.get(projection_key, []) or []:
            if object_id in seen:
                continue
            seen.add(object_id)
            result.append(object_id)

    return result


def clear_legacy_linesplan_2d_output():
    """
    V19: dọn output 2D của các phiên bản cũ dưới DRAWING_2D.

    Chỉ đụng tới cây layer do MODEL112 tự sinh. SOURCE_3D không bị ảnh hưởng.
    Mục tiêu là tránh còn các sublayer Profile/HalfBreadth/BodyPlan cũ làm rối.
    """
    try:
        layer_names = list(
            rs.LayerNames() or []
        )
    except Exception:
        layer_names = []

    prefix = (
        LINESPLAN_DRAWING_ROOT +
        u"::"
    )

    legacy_layers = [
        name for name in layer_names
        if TEXT_TYPE(name).startswith(prefix)
    ]

    # Xóa object 2D cũ trước, sau đó xóa layer con từ sâu lên nông.
    for layer_name in legacy_layers:
        try:
            object_ids = rs.ObjectsByLayer(
                layer_name
            ) or []
            if object_ids:
                rs.DeleteObjects(
                    object_ids
                )
        except Exception:
            pass

    legacy_layers.sort(
        key=lambda name: TEXT_TYPE(name).count("::"),
        reverse=True
    )

    for layer_name in legacy_layers:
        try:
            if rs.IsLayerEmpty(layer_name):
                rs.DeleteLayer(layer_name)
        except Exception:
            pass

    ensure_nested_layer(
        LINESPLAN_2D_OUTPUT_LAYER
    )


def clear_linesplan_2d_variant(layer_path, sticky_key):
    """Remove one MODEL112 drawing variant, including results from older sessions.

    Do not touch Rhino's shared Make2D layers or unrelated user geometry.
    """
    clear_sticky_objects(sticky_key)
    layer_names = [name for name in (rs.LayerNames() or [])
                   if name == layer_path or name.startswith(layer_path + u"::")]
    for name in layer_names:
        try:
            ids = rs.ObjectsByLayer(name) or []
            if ids:
                rs.DeleteObjects(ids)
        except Exception:
            pass
    for name in sorted(layer_names, key=lambda value: value.count("::"), reverse=True):
        if name != layer_path:
            try:
                if rs.IsLayerEmpty(name):
                    rs.DeleteLayer(name)
            except Exception:
                pass
    ensure_nested_layer(layer_path)


def remove_empty_make2d_layers():
    """Delete Rhino's empty automatic Make2D sublayers; preserve nonempty/user layers."""
    try:
        names = list(rs.LayerNames() or [])
    except Exception:
        return
    names = [name for name in names
             if name == u"Make2D" or name.startswith(u"Make2D::")]
    try:
        # Rhino sometimes makes Make2D::Visible the current layer.
        # Switch to our safe layer before deleting Rhino's empty tree.
        current = rs.CurrentLayer()
        if current == u"Make2D" or current.startswith(u"Make2D::"):
            ensure_nested_layer(LAYER_KHUNG)
            rs.CurrentLayer(LAYER_KHUNG)
    except Exception:
        pass
    for name in sorted(names, key=lambda value: value.count("::"), reverse=True):
        try:
            if rs.IsLayerEmpty(name) and name != rs.CurrentLayer():
                rs.DeleteLayer(name)
        except Exception:
            pass


def hide_rhino_make2d_legacy_layers():
    """RC11: Hide previous Rhino Make2D objects without deleting user geometry.

    Rhino may leave user/legacy drawing curves on Make2D::Visible even after
    MODEL112 moves *new* curves to DRAWING_2D. These old curves look like
    duplicate output in Top view. We only hide the standard Rhino Make2D tree.
    """
    try:
        names = list(rs.LayerNames() or [])
    except Exception:
        return (0, 0)
    names = [name for name in names
             if name == u"Make2D" or name.startswith(u"Make2D::")]
    if not names:
        return (0, 0)
    hidden_objects = 0
    for name in names:
        try:
            hidden_objects += len(rs.ObjectsByLayer(name) or [])
        except Exception:
            pass
    try:
        current = TEXT_TYPE(rs.CurrentLayer())
        if current == u"Make2D" or current.startswith(u"Make2D::"):
            ensure_nested_layer(LAYER_KHUNG)
            rs.CurrentLayer(LAYER_KHUNG)
    except Exception:
        pass
    # Hide children first and then the parent, keeping all previous geometry.
    for name in sorted(names, key=lambda value: value.count("::"), reverse=True):
        try:
            rs.LayerVisible(name, False)
        except Exception:
            pass
    if hidden_objects:
        Rhino.RhinoApp.WriteLine(
            "MODEL112 RC11: hid %d old objects on Rhino Make2D layers "
            "(not deleted; re-enable Make2D layer to see them)." % hidden_objects)
    return (len(names), hidden_objects)


def tag_linesplan_projection(object_ids, view_name, variant_name):
    """Attach inspectable metadata to generated curves for future diagnostics."""
    for oid in (object_ids or []):
        try:
            obj = sc.doc.Objects.FindId(oid)
            if obj is None:
                continue
            attributes = obj.Attributes.Duplicate()
            attributes.SetUserString("MODEL112_2D_VIEW", view_name)
            attributes.SetUserString("MODEL112_2D_VARIANT", variant_name)
            attributes.SetUserString("MODEL112_2D_RELEASE", "RC14")
            sc.doc.Objects.ModifyAttributes(obj, attributes, True)
        except Exception:
            pass


def linesplan_curve_signature(curve, tolerance):
    """Conservative shape fingerprint, independent of curve direction.

    Only eliminate an exact-looking repeated projection inside ONE view.
    Separate views are never compared, to preserve the lines plan layout.
    """
    try:
        tol = max(float(tolerance), 1.0e-8)
        bbox = curve.GetBoundingBox(True)
        def quantize(value):
            return int(round(float(value) / tol))
        bbox_key = tuple(quantize(value) for value in (
            bbox.Min.X, bbox.Min.Y, bbox.Max.X, bbox.Max.Y,
            bbox.Min.Z, bbox.Max.Z))
        length_key = quantize(curve.GetLength())
        t0, t1 = float(curve.Domain.T0), float(curve.Domain.T1)
        samples = []
        for k in range(9):
            point = curve.PointAt(t0 + (t1 - t0) * float(k) / 8.0)
            samples.append((quantize(point.X), quantize(point.Y),
                            quantize(point.Z)))
        a = tuple(samples)
        b = tuple(reversed(samples))
        return (bbox_key, length_key, a if a <= b else b)
    except Exception:
        return None


def remove_duplicate_linesplan_curves(curve_ids):
    """Prune truly coincident projected curves, without merging nearby lines."""
    tolerance = max(float(sc.doc.ModelAbsoluteTolerance) * 0.05, 1.0e-8)
    signatures = set()
    result = []
    for object_id in curve_ids:
        obj = sc.doc.Objects.FindId(object_id)
        if obj is None or not isinstance(obj.Geometry, rg.Curve):
            continue
        signature = linesplan_curve_signature(obj.Geometry, tolerance)
        if signature is not None and signature in signatures:
            # Preserve the curve if Rhino refused deletion (locked object etc.).
            if sc.doc.Objects.Delete(object_id, True):
                continue
        if signature is not None:
            signatures.add(signature)
        result.append(object_id)
    return result


def linesplan_source_layer_visibility():
    """Capture source visibility so a failed Make2D can restore it."""
    layers = [name for name in (rs.LayerNames() or [])
              if name == LINESPLAN_SOURCE_ROOT or
              name.startswith(LINESPLAN_SOURCE_ROOT + u"::")]
    return [(name, bool(rs.IsLayerVisible(name)))
            for name in sorted(layers, key=lambda value: value.count("::"))]


def set_linesplan_source_layers_visible(visible):
    for name, _ in linesplan_source_layer_visibility():
        rs.LayerVisible(name, bool(visible))


def restore_linesplan_source_layer_visibility(states):
    for name, visible in states:
        if rs.IsLayer(name):
            rs.LayerVisible(name, visible)


def arrange_linesplan_views_standard(
    profile_ids,
    plan_ids,
    body_ids,
    params
):
    """
    Bố trí cố định bản vẽ đường hình V19:

        HÌNH ĐỨNG (Profile)        BODY PLAN
        [gốc tại 0,0]              [bên phải, chung baseline]

        HÌNH BẰNG (Half-Breadth)
        [nằm ngay dưới Profile, thẳng cột X]

    Dùng bounding box thực của Make2D thay vì vị trí mặc định của Rhino, nên
    số lượng STA/WL/CD thay đổi vẫn không làm ba hình chiếu chạy lung tung.
    """
    units = float(
        params.units_per_meter
    )

    B_local = float(
        params.beam
    )
    H_local = float(
        params.depth
    )

    # Khoảng hở theo kích thước vật lý, tối thiểu 0.75 m.
    minimum_gap = model_units_from_meters(
        0.75,
        units
    )

    gap_x = max(
        minimum_gap,
        B_local * 0.30,
        H_local * 0.25
    )

    gap_y = max(
        minimum_gap,
        B_local * 0.20,
        H_local * 0.20
    )

    profile_width, profile_height = objects_bbox_size_xy(
        profile_ids
    )
    plan_width, plan_height = objects_bbox_size_xy(
        plan_ids
    )
    body_width, body_height = objects_bbox_size_xy(
        body_ids
    )

    # RC12: place the drawing to the RIGHT of original 3D hull (X=0..L).
    # In Top view it is visually distinct from MODEL112 hull/source objects,
    # even if the user has left original Model 1 hull layers visible.
    drawing_origin_x = float(params.length) + max(gap_x, B_local * 0.5)
    drawing_origin_y = 0.0
    move_objects_to_anchor(
        profile_ids,
        drawing_origin_x,
        drawing_origin_y
    )

    # 2) Body Plan nằm bên phải hình đứng và cùng đường baseline (Y = 0).
    body_anchor_x = (
        drawing_origin_x +
        profile_width +
        gap_x
    )

    move_objects_to_anchor(
        body_ids,
        body_anchor_x,
        drawing_origin_y
    )

    # 3) Hình bằng nằm dưới hình đứng; mép trên cách baseline một gap_y.
    # move_objects_to_anchor dùng góc trái-dưới, nên phải trừ cả chiều cao plan.
    plan_anchor_y = drawing_origin_y - (
        plan_height +
        gap_y
    )

    move_objects_to_anchor(
        plan_ids,
        drawing_origin_x,
        plan_anchor_y
    )

    return {
        "profile_anchor": (drawing_origin_x, drawing_origin_y),
        "plan_anchor": (drawing_origin_x, plan_anchor_y),
        "body_anchor": (body_anchor_x, drawing_origin_y),
        "gap_x": gap_x,
        "gap_y": gap_y,
        "profile_size": (profile_width, profile_height),
        "plan_size": (plan_width, plan_height),
        "body_size": (body_width, body_height)
    }


def linesplan_orthographic_rotation(world_view_name):
    """Map world coordinates onto drawing axes before flattening:

       Front / Profile: (X, Z)
       Top / HalfBreadth: (X, Y)
       Right / BodyPlan: (Y, Z)

    All mappings are rigid rotations. The next step projects onto WorldXY.
    This is independent of Rhino viewports, Make2D layout, and saved settings.
    """
    view = TEXT_TYPE(world_view_name).strip().lower()
    transform = rg.Transform.Identity
    if view == "top":
        return transform
    if view == "front":
        # Rotation -90 degrees around X: (x,y,z) -> (x,z,-y)
        transform.M00 = 1.0
        transform.M01 = 0.0
        transform.M02 = 0.0
        transform.M10 = 0.0
        transform.M11 = 0.0
        transform.M12 = 1.0
        transform.M20 = 0.0
        transform.M21 = -1.0
        transform.M22 = 0.0
        return transform
    if view == "right":
        # Cyclic rotation: (x,y,z) -> (y,z,x)
        transform.M00 = 0.0
        transform.M01 = 1.0
        transform.M02 = 0.0
        transform.M10 = 0.0
        transform.M11 = 0.0
        transform.M12 = 1.0
        transform.M20 = 1.0
        transform.M21 = 0.0
        transform.M22 = 0.0
        return transform
    raise Exception(u"Hướng chiếu 2D không hỗ trợ: %s" % world_view_name)


def linesplan_project_curve_xy(source_curve, rotation):
    """Project a SOURCE_3D curve to one exact plane in RhinoCommon.

    The source is DUPLICATED: no viewport changes, no Make2D side effects,
    no change to the original hull and no new curves on Rhino's Make2D layers.
    """
    duplicate = source_curve.DuplicateCurve()
    if duplicate is None:
        return None
    if not duplicate.Transform(rotation):
        return None
    try:
        projected = rg.Curve.ProjectToPlane(duplicate, rg.Plane.WorldXY)
    except Exception:
        projected = None
    if projected is None:
        try:
            flatten = rg.Transform.PlanarProjection(rg.Plane.WorldXY)
            if duplicate.Transform(flatten):
                projected = duplicate
        except Exception:
            pass
    return projected


def run_make2d_current_view(
    source_ids,
    world_view_name,
    output_layer_name,
    anchor_x=None,
    anchor_y=None
):
    """RC12: deterministic orthographic RhinoCommon projection, NOT -Make2D.

    Build one single 2D view from its OWN filtered source curves. The former
    -Make2D macro depended on the active viewport and created hundreds of
    extraneous lines when full source families were passed to each view.
    """
    rotation = linesplan_orthographic_rotation(world_view_name)
    tolerance = max(float(sc.doc.ModelAbsoluteTolerance) * 0.05, 1.0e-8)
    unique_ids = []
    seen = set()
    for oid in (source_ids or []):
        if oid not in seen:
            seen.add(oid)
            unique_ids.append(oid)

    result = []
    signatures = set()
    skipped = 0
    duplicates = 0
    try:
        for oid in unique_ids:
            obj = sc.doc.Objects.FindId(oid)
            if obj is None or not isinstance(obj.Geometry, rg.Curve):
                skipped += 1
                continue
            curve = linesplan_project_curve_xy(obj.Geometry, rotation)
            if curve is None:
                skipped += 1
                continue
            try:
                if curve.GetLength() <= tolerance:
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue
            signature = linesplan_curve_signature(curve, tolerance)
            if signature is not None and signature in signatures:
                duplicates += 1
                continue
            new_id = add_curve_to_named_layer(curve, output_layer_name)
            if new_id is None:
                raise Exception(u"Không thêm được curve chiếu vào layer: %s" % output_layer_name)
            result.append(new_id)
            if signature is not None:
                signatures.add(signature)

        if not result:
            raise Exception(u"Hướng %s không tạo được đường chiếu 2D." % world_view_name)
        if anchor_x is not None and anchor_y is not None:
            move_objects_to_anchor(result, anchor_x, anchor_y)
        Rhino.RhinoApp.WriteLine(
            "MODEL112 RC14 ORTHO %s: input=%d, drawn=%d, "
            "duplicates=%d, skipped=%d" % (
                world_view_name, len(unique_ids), len(result), duplicates, skipped))
        return result
    except Exception:
        delete_object_ids(result)
        raise


def make2d_records_to_layers(
    records,
    world_view_name,
    output_parent_layer,
    individual_layers
):
    """
    Helper tương thích code cũ. V19 luôn gom mọi record rồi Make2D một lần;
    không còn nhánh tạo layer con theo từng label.
    """
    records = list(
        records or []
    )

    if not records:
        return []

    source_ids = []

    for record in records:
        source_ids.extend(
            record.get(
                "ids",
                []
            )
        )

    return run_make2d_current_view(
        source_ids,
        world_view_name,
        output_parent_layer,
        None,
        None
    )



def hull_feature_records_for_projection(
    records,
    projection_key
):
    result = []

    for record in records or []:
        ids = list(
            record.get(
                projection_key,
                []
            )
        )

        if not ids:
            continue

        result.append(
            {
                "label": record.get(
                    "label",
                    "HullLine"
                ),
                "ids": ids
            }
        )

    return result


def linesplan_export_feature_ids(records, params, projection_key):
    """Chỉ đưa các đường đặc trưng đang được bật vào bản xuất 2D."""
    enabled = {
        "Keel": bool(getattr(params, "show_keel_curve", True)),
        "Chine": bool(getattr(params, "show_chine_curves", True)),
        "Sheer": bool(getattr(params, "show_sheer_curve", True)),
        "Transom": bool(getattr(params, "show_transom_frame", True))
    }
    visible_records = [
        record for record in (records or [])
        if enabled.get(record.get("kind", ""), True)
    ]
    return collect_hull_feature_projection_ids(
        visible_records, projection_key
    )


def split_linesplan_longitudinal_at_mid(curve, mid_x, tolerance):
    """Chia rail theo X=Lmax/2 trước khi chiếu Body Plan."""
    bbox = curve.GetBoundingBox(True)
    if bbox.Max.X <= mid_x + tolerance:
        return [curve.DuplicateCurve()], []
    if bbox.Min.X >= mid_x - tolerance:
        return [], [curve.DuplicateCurve()]

    parameters = []
    plane = rg.Plane(rg.Point3d(mid_x, 0.0, 0.0), rg.Vector3d.XAxis)
    try:
        events = Rhino.Geometry.Intersect.Intersection.CurvePlane(
            curve, plane, tolerance)
        parameters = [float(event.ParameterA) for event in (events or [])]
    except Exception:
        pass

    # Một số bản Rhino không trả intersection nếu curve tiếp xúc mặt
    # phẳng tại knot. Nội suy nghiệm X(t)=mid_x từ các điểm trên domain.
    if not parameters:
        t0, t1 = float(curve.Domain.T0), float(curve.Domain.T1)
        previous_t = t0
        previous_x = float(curve.PointAt(t0).X) - mid_x
        for index in range(1, 65):
            current_t = t0 + (t1 - t0) * float(index) / 64.0
            current_x = float(curve.PointAt(current_t).X) - mid_x
            if previous_x * current_x <= 0.0:
                lo, hi = previous_t, current_t
                sign_lo = previous_x
                for iteration in range(36):
                    middle = 0.5 * (lo + hi)
                    middle_x = float(curve.PointAt(middle).X) - mid_x
                    if sign_lo * middle_x <= 0.0:
                        hi = middle
                    else:
                        lo = middle
                        sign_lo = middle_x
                parameters.append(0.5 * (lo + hi))
            previous_t, previous_x = current_t, current_x

    t0, t1 = float(curve.Domain.T0), float(curve.Domain.T1)
    candidate_parameters = sorted(value for value in parameters
                                  if t0 + 1.0e-10 < value < t1 - 1.0e-10)
    parameter_tolerance = max(abs(t1 - t0) * 1.0e-8, 1.0e-10)
    parameters = []
    for value in candidate_parameters:
        if not parameters or abs(value - parameters[-1]) > parameter_tolerance:
            parameters.append(value)
    if not parameters:
        raise Exception(u"Không chia được đường keel/chine/sheer tại Lmax/2.")
    pieces = curve.Split(parameters)
    if not pieces:
        raise Exception(u"Split đường keel/chine/sheer tại Lmax/2 thất bại.")

    aft, fore = [], []
    for piece in pieces:
        middle_t = 0.5 * (piece.Domain.T0 + piece.Domain.T1)
        middle_x = float(piece.PointAt(middle_t).X)
        if middle_x < mid_x - tolerance:
            aft.append(piece)
        elif middle_x > mid_x + tolerance:
            fore.append(piece)
        else:
            # Đoạn ở đúng mặt phẳng giữa thuộc cả hai phía.
            aft.append(piece.DuplicateCurve())
            fore.append(piece)
    return aft, fore


def linesplan_export_temporary_curves(source_ids, tolerance, created_ids,
                                      mirror_to_port=False, mid_x=None,
                                      longitudinal_side=None):
    """Tạo bản sao một mạn cho Make2D; không sửa SOURCE_3D gốc."""
    temporary_layer = LINESPLAN_ROOT + u"::TEMP_EXPORT"
    ensure_nested_layer(temporary_layer)
    try:
        rs.LayerLocked(temporary_layer, False)
        rs.LayerVisible(temporary_layer, True)
    except Exception:
        pass
    unique_source_ids = []
    seen = set()
    for object_id in source_ids or []:
        if object_id not in seen:
            seen.add(object_id)
            unique_source_ids.append(object_id)

    mirror = rg.Transform.Identity
    mirror.M11 = -1.0  # Y -> -Y, giữ nguyên X và Z.
    copied_ids = []
    for object_id in unique_source_ids:
        rhino_object = sc.doc.Objects.FindId(object_id)
        geometry = rhino_object.Geometry if rhino_object else None
        if not isinstance(geometry, rg.Curve):
            continue
        for curve in keep_curves_starboard_half([geometry], tolerance):
            if longitudinal_side is not None:
                aft, fore = split_linesplan_longitudinal_at_mid(
                    curve, mid_x, tolerance)
                pieces = aft if longitudinal_side == "aft" else fore
            else:
                pieces = [curve]
            for piece in pieces:
                if mirror_to_port:
                    piece.Transform(mirror)
                copied_id = add_curve_to_named_layer(piece, temporary_layer)
                if copied_id is not None:
                    created_ids.append(copied_id)
                    copied_ids.append(copied_id)
    return copied_ids


def partition_linesplan_stations(station_records, mid_x, tolerance):
    """Chia sườn theo vị trí vật lý, không phụ thuộc số sườn hay thứ tự nhập."""
    aft_records, mid_records, fore_records = [], [], []
    for record in sorted(
        station_records,
        key=lambda item: float(item.get("value_model", 0.0))
    ):
        x_value = float(record.get("value_model", 0.0))
        if x_value < mid_x - tolerance:
            aft_records.append(record)
        elif x_value > mid_x + tolerance:
            fore_records.append(record)
        else:
            mid_records.append(record)
    return aft_records, mid_records, fore_records


def create_linesplan_export_views(params, station_records, waterline_records,
                                  buttock_records, hull_line_records,
                                  output_layer, full_views=False):
    """Dựng bản vẽ 3 hình chiếu từ SOURCE_3D, không sửa hình học nguồn.

    full_views=False -> 2D Export: half-breadth chỉ một mạn và Body Plan
                        chia sườn đuôi trái / mũi phải tại Lmax/2.
    full_views=True  -> Make2D đầy đủ: hình bằng và Body Plan đủ HAI MẠN,
                        không chia sườn, cho phép kiểm tra toàn bộ đường.
    Hai chế độ khác *nội dung*, không chỉ khác layer. Cùng dùng phép chiếu
    RhinoCommon và loại đường trùng; không gọi lệnh Rhino -Make2D.
    """
    tolerance = get_linesplan_intersection_tolerance(
        float(params.units_per_meter)
    )
    temporary_ids = []
    temporary_layer = LINESPLAN_ROOT + u"::TEMP_EXPORT"

    mid_x = float(params.length) * 0.5

    def copy_one_side(ids, mirror=False, longitudinal_side=None):
        return linesplan_export_temporary_curves(
            ids, tolerance, temporary_ids, mirror, mid_x,
            longitudinal_side
        )

    try:
        # Hình đứng giữ đủ chiều dài; chỉ dùng một mạn đối xứng để không
        # lặp đường trùng nhau. Hình bằng chỉ thể hiện mạn Starboard.
        common_source = (
            collect_record_object_ids(station_records) +
            collect_record_object_ids(waterline_records) +
            collect_record_object_ids(buttock_records)
        )
        profile_source = copy_one_side(
            common_source + linesplan_export_feature_ids(
                hull_line_records, params, "profile_ids"
            )
        )
        profile_ids = run_make2d_current_view(
            profile_source, "Front", output_layer
        )

        plan_feature_source = (
            common_source + linesplan_export_feature_ids(
                hull_line_records, params, "plan_ids"
            )
        )
        plan_source = copy_one_side(plan_feature_source)
        if full_views:
            # Make2D đầy đủ: giữ cả mạn +Y và mạn -Y ở hình chiếu bằng.
            # 2D Export chỉ có một mạn để phục vụ bản vẽ nửa chiều rộng.
            plan_source.extend(copy_one_side(plan_feature_source, mirror=True))
        plan_ids = run_make2d_current_view(
            plan_source, "Top", output_layer
        )

        if full_views:
            # MAKE2D ĐẦY ĐỦ: cả hai mạn của TẤT CẢ tiết diện;
            # không ghép đuôi/mũi lên cùng hai nửa như bản Export.
            all_station_ids = collect_record_object_ids(station_records)
            if not all_station_ids:
                raise Exception(u"Không có Station để dựng hình sườn đầy đủ.")
            body_source = copy_one_side(all_station_ids)
            body_source.extend(copy_one_side(all_station_ids, mirror=True))
            # Đủ các đường tham chiếu và đặc trưng về hai mạn.
            guide_ids = (collect_record_object_ids(waterline_records) +
                         collect_record_object_ids(buttock_records))
            body_source.extend(copy_one_side(guide_ids))
            body_source.extend(copy_one_side(guide_ids, mirror=True))
            hull_feature_ids = linesplan_export_feature_ids(
                hull_line_records, params, "body_ids")
            body_source.extend(copy_one_side(hull_feature_ids))
            body_source.extend(copy_one_side(hull_feature_ids, mirror=True))
        else:
            # EXPORT 2D quy ước: đuôi trái, mũi phải, sườn giữa chung.
            # Giữ nguyên thuật toán phân chia tại Lmax/2 của RC12/RC13.
            # Chia theo X=Lmax/2. Sườn đúng giữa là tiết diện chung: hai
            # nửa đối xứng sang hai phía Body Plan, chỉ tồn tại một sườn 3D.
            aft_records, mid_records, fore_records = partition_linesplan_stations(
                station_records, mid_x, tolerance
            )
            aft_source = collect_record_object_ids(aft_records)
            mid_source = collect_record_object_ids(mid_records)
            fore_source = collect_record_object_ids(fore_records)
            if not aft_source or not fore_source:
                raise Exception(
                    u"Bản xuất cần ít nhất một sườn với X < Lmax/2 và "
                    u"một sườn với X > Lmax/2."
                )

            # Right view: -Y is on the left; +Y is on the right.
            body_source = copy_one_side(aft_source, mirror=True)
            body_source.extend(copy_one_side(mid_source, mirror=True))
            body_source.extend(copy_one_side(mid_source))
            body_source.extend(copy_one_side(fore_source))

            # WL/CD chỉ là các đường tham chiếu ở hai phía Body Plan.
            guides = (
                collect_record_object_ids(waterline_records) +
                collect_record_object_ids(buttock_records)
            )
            body_source.extend(copy_one_side(guides))
            body_source.extend(copy_one_side(guides, mirror=True))
            # Đường khung dọc cũng theo quy tắc đuôi trái, mũi phải. Cắt
            # tại Lmax/2 trước khi chiếu để chine/sheer không chạy xuyên
            # sang nửa sai của Body Plan.
            longitudinal_ids = linesplan_export_feature_ids(
                [r for r in hull_line_records
                 if r.get("kind") in ("Keel", "Chine", "Sheer")],
                params, "body_ids")
            body_source.extend(copy_one_side(
                longitudinal_ids, mirror=True, longitudinal_side="aft"))
            body_source.extend(copy_one_side(
                longitudinal_ids, longitudinal_side="fore"))
            body_source.extend(copy_one_side(linesplan_export_feature_ids(
                [r for r in hull_line_records if r.get("kind") == "Transom"],
                params, "body_ids"
            ), mirror=True))
        body_ids = run_make2d_current_view(
            body_source, "Right", output_layer
        )
        return profile_ids, plan_ids, body_ids
    finally:
        delete_object_ids(temporary_ids)
        try:
            if rs.IsLayerEmpty(temporary_layer):
                rs.DeleteLayer(temporary_layer)
        except Exception:
            pass


def create_linesplan_make2d(
    params,
    source_data,
    individual_layers=False,
    export_drawing=False
):
    """
    MODEL 112 V21 RC14 - TẠO HAI LOẠI BẢN VẼ 2D ĐỘC LẬP.

    Nguyên tắc:
    - Mỗi HÌNH CHIẾU chỉ gọi Make2D MỘT LẦN cho toàn bộ họ đường cần thiết.
      Nhờ vậy các đường trong cùng hình giữ đúng tương quan, không bị mỗi STA/WL
      tự nhận một gốc Make2D riêng rồi chạy tản ra.
    - Make2D đầy đủ và 2D export có layer ngang cấp riêng biệt.
    - Profile ở trái/trên, Half-Breadth ngay dưới Profile, Body Plan bên phải.
    - RC14: MAKE2D ĐẦY ĐỦ giữ cả hai mạn trên hình bằng và hình sườn;
        2D EXPORT giữ nửa hình bằng và chia sườn đuôi trái/mũi phải.
        Cả hai tạo đủ ba hình chiếu, nội dung thật sự khác nhau.
    - RhinoCommon chiếu trực tiếp; KHÔNG chạy -Make2D ba lần.
    - individual_layers chỉ được giữ để tương thích lời gọi cũ; toàn bộ output
      2D luôn nằm chung trong DRAWING_2D.
    """
    output_layer = (LINESPLAN_EXPORT_OUTPUT_LAYER if export_drawing
                    else LINESPLAN_2D_OUTPUT_LAYER)
    sticky_key = (LINESPLAN_EXPORT_STICKY_KEY if export_drawing
                  else LINESPLAN_2D_STICKY_KEY)
    clear_linesplan_2d_variant(output_layer, sticky_key)
    if not export_drawing:
        clear_legacy_linesplan_2d_output()
    rs.LayerVisible(output_layer, True)

    if not source_data:
        raise Exception(
            u"Chưa có dữ liệu đường cắt 3D để Make2D."
        )

    station_records = list(
        source_data.get(
            "station_records",
            []
        )
    )
    waterline_records = list(
        source_data.get(
            "waterline_records",
            []
        )
    )
    buttock_records = list(
        source_data.get(
            "buttock_records",
            []
        )
    )
    hull_line_records = list(
        source_data.get(
            "hull_line_records",
            []
        )
    )

    if not (
        station_records or
        waterline_records or
        buttock_records or
        hull_line_records
    ):
        raise Exception(
            u"Dữ liệu đường cắt 3D không có record hợp lệ."
        )

    # RC14: two distinct layouts, one reliable projection engine.
    # FULL: both sides in HalfBreadth and BodyPlan; EXPORT: half-breadth,
    # aft-left/fore-right BodyPlan. No Rhino -Make2D macros or duplicates.
    profile_ids, plan_ids, body_ids = create_linesplan_export_views(
        params, station_records, waterline_records,
        buttock_records, hull_line_records, output_layer,
        full_views=(not export_drawing)
    )

    # Tag each of three orthographic projections for inspection.
    drawing_variant_name = "EXPORT_2D" if export_drawing else "DRAWING_2D"
    tag_linesplan_projection(profile_ids, "Profile", drawing_variant_name)
    tag_linesplan_projection(plan_ids, "HalfBreadth", drawing_variant_name)
    tag_linesplan_projection(body_ids, "BodyPlan", drawing_variant_name)

    # Ép lại layer lần cuối để mọi curve 2D chắc chắn ở chung một layer.
    all_2d_ids = (
        profile_ids +
        plan_ids +
        body_ids
    )
    if not all_2d_ids:
        raise Exception(u"Make2D không tạo được đường 2D nào; hãy kiểm tra nguồn và tùy chọn Rhino.")

    set_objects_layer(
        all_2d_ids,
        output_layer
    )

    layout_info = arrange_linesplan_views_standard(
        profile_ids,
        plan_ids,
        body_ids,
        params
    )

    # MODE 112 RC10: retain only ONE 2D result in the document.
    # Switch Make2D <-> Export by regenerating the desired variant from SOURCE_3D.
    if export_drawing:
        clear_linesplan_2d_variant(LINESPLAN_2D_OUTPUT_LAYER,
                                   LINESPLAN_2D_STICKY_KEY)
    else:
        clear_linesplan_2d_variant(LINESPLAN_EXPORT_OUTPUT_LAYER,
                                   LINESPLAN_EXPORT_STICKY_KEY)
    remove_empty_make2d_layers()
    legacy_layer_count, legacy_object_count = hide_rhino_make2d_legacy_layers()
    Rhino.RhinoApp.WriteLine(
        "MODEL112 RC14 Mode2 %s: Profile=%d, HalfBreadth=%d, BodyPlan=%d, "
        "RhinoMake2DLegacy=%d objects/%d layers" % (
            drawing_variant_name, len(profile_ids), len(plan_ids),
            len(body_ids), legacy_object_count, legacy_layer_count))

    sc.sticky[sticky_key] = list(all_2d_ids)

    # Sau khi tạo xong giữ Top view để người dùng thấy ngay bản vẽ 2D đã sắp xếp.
    try:
        rs.Command(
            "_SetView _World _Top",
            False
        )
    except Exception:
        pass

    # Zoom after the UI hides the other drawing and SOURCE_3D.
    sc.doc.Views.Redraw()

    return {
        "profile_ids": profile_ids,
        "plan_ids": plan_ids,
        "body_ids": body_ids,
        "all_ids": all_2d_ids,
        "output_layer": output_layer,
        "layout_info": layout_info
    }


# =============================================================================
# MODULE 13: TÍNH TOÁN THỦY TĨNH
# =============================================================================
# Mục đích:
# - Dùng trực tiếp hình dáng vỏ tàu hiện tại của Chế độ 1.
# - Join các mặt vỏ thành shell liên tục, không cần đóng boong.
# - Cắt shell tại mớn nước rồi cap mặt đường nước để tạo solid phần chìm.
# - Từ thể tích phần chìm, Rhino tính V, trọng tâm thể tích -> LCB, TCB, KB.
# - Từ mặt đường nước của phần chìm, chương trình tính Awp, LCF, LWL, BWL,
#   mô men quán tính mặt đường nước, BM và KM.
# - Hình học dùng để tính chỉ tồn tại tạm thời và được xóa sau khi hoàn tất.
#
# QUY ƯỚC TỌA ĐỘ:
# - X = 0 tại mốc đuôi của mô hình, X tăng về phía mũi.
# - Y = 0 tại mặt phẳng dọc tâm.
# - Z = BaselineZ tại đường cơ bản.
# - LCB và LCF được báo theo mét tính từ X = 0.
# =============================================================================

HYDRO_RESULT_STICKY_KEY = "MODEL_112_HYDRO_RESULTS"


def hydro_brep_area(brep):
    """Trả diện tích Brep để chọn thành phần vỏ chính khi Join."""
    if brep is None:
        return 0.0
    try:
        props = rg.AreaMassProperties.Compute(brep)
        if props is not None:
            return abs(float(props.Area))
    except Exception:
        pass
    try:
        bbox = brep.GetBoundingBox(True)
        if bbox is not None:
            dx = max(0.0, float(bbox.Max.X - bbox.Min.X))
            dy = max(0.0, float(bbox.Max.Y - bbox.Min.Y))
            dz = max(0.0, float(bbox.Max.Z - bbox.Min.Z))
            return dx * dy + dx * dz + dy * dz
    except Exception:
        pass
    return 0.0


def hydro_naked_edge_count(brep):
    """Đếm số cạnh hở của một Brep."""
    if brep is None:
        return 999999
    try:
        edges = brep.DuplicateNakedEdgeCurves(True, True)
        return len(edges) if edges is not None else 0
    except Exception:
        return 999999



def hydro_native_collect_breps(object_ids):
    """
    Chuyển danh sách GUID trong tài liệu Rhino thành Brep geometry.
    Chỉ dùng cho geometry tạm của module thủy tĩnh.
    """
    result = []

    for object_id in object_ids or []:
        try:
            brep = rs.coercebrep(object_id)
        except Exception:
            brep = None

        if brep is not None:
            result.append(
                (
                    object_id,
                    brep
                )
            )

    return result



def hydro_native_best_shell_from_ids(object_ids):
    """
    Chọn Brep tốt nhất dù CHƯA phải solid.

    Tiêu chí:
    1. Ưu tiên IsSolid.
    2. Nếu chưa solid, ưu tiên số naked edge nhỏ nhất.
    3. Nếu số naked edge bằng nhau, ưu tiên diện tích Brep lớn hơn.

    Đây là sửa lỗi logic quan trọng:
    từng tìm được candidate chỉ còn 4 naked edges nhưng bỏ đi
    vì candidate.IsSolid == False, rồi quay về shell 20 cạnh hở.
    """
    best = None
    best_is_solid = False
    best_naked = 999999
    best_area = -1.0

    for object_id, brep in hydro_native_collect_breps(
        object_ids
    ):
        if brep is None:
            continue

        candidate = brep.DuplicateBrep()

        # Dùng lại logic AutoJoinEdge trước khi đánh giá.
        if not candidate.IsSolid:
            repaired = hydro_auto_join_naked_edges(
                candidate
            )

            if repaired is not None:
                candidate = repaired

        is_solid = bool(
            candidate.IsSolid
        )

        naked = hydro_naked_edge_count(
            candidate
        )

        area = hydro_brep_area(
            candidate
        )

        better = False

        if is_solid and not best_is_solid:
            better = True
        elif is_solid == best_is_solid:
            if naked < best_naked:
                better = True
            elif naked == best_naked and area > best_area:
                better = True

        if better:
            best = candidate.DuplicateBrep()
            best_is_solid = is_solid
            best_naked = naked
            best_area = area

    if best is not None:
        print(
            (
                "Hydro Native BestShell V7.8 | "
                "solid=%s | naked=%d | area=%.3f"
            ) % (
                str(best_is_solid),
                best_naked,
                best_area
            )
        )

    return best



def hydro_native_largest_solid_from_ids(object_ids):
    """Lấy solid có thể tích lớn nhất trong các object tạm của Rhino."""
    best = None
    best_volume = -1.0

    for object_id, brep in hydro_native_collect_breps(object_ids):
        if brep is None:
            continue

        candidate = brep

                                                                        
        # trên bản sao geometry trước khi quyết định thất bại.
        if not candidate.IsSolid:
            repaired = hydro_auto_join_naked_edges(
                candidate
            )

            if repaired is not None:
                candidate = repaired

        if not candidate.IsSolid:
            continue

        try:
            props = rg.VolumeMassProperties.Compute(candidate)
        except Exception:
            props = None

        if props is None:
            continue

        volume = abs(float(props.Volume))

        if volume > best_volume:
            best_volume = volume
            best = candidate

    if best is None:
        return None

    return best.DuplicateBrep()


def hydro_native_temp_ids_since(before_ids, explicit_ids=None):
    """
    Thu thập toàn bộ object phát sinh sau khi bắt đầu một chuỗi command.
    explicit_ids được cộng thêm để bắt các object cũ bị Join/Cap thay thế.
    """
    current_ids = set(rs.AllObjects() or [])
    result = set(current_ids.difference(before_ids))

    for object_id in explicit_ids or []:
        if object_id in current_ids:
            result.add(object_id)

    try:
        for object_id in rs.LastCreatedObjects(select=False) or []:
            if object_id in current_ids:
                result.add(object_id)
    except Exception:
        pass

    try:
        for object_id in rs.SelectedObjects() or []:
            if object_id in current_ids:
                result.add(object_id)
    except Exception:
        pass

    return list(result)


def hydro_try_rhino_native_solid(raw_breps):
    """
    DÙNG TRỰC TIẾP CÁC LỆNH CÓ SẴN CỦA RHINO.

    Trình tự thử:
        1. Đưa bản sao các surface vào tài liệu Rhino.
        2. _CreateSolid
        3. Nếu chưa được: _Join
        4. _Cap
        5. Kiểm tra IsSolid và VolumeMassProperties.

    Tất cả object đều là bản sao TẠM và được xóa sau khi hoàn tất.
    Vỏ tàu của Chế độ 1 hoàn toàn không bị sửa.

    Lưu ý:
    - Không tự động dùng _JoinEdge vì JoinEdge có thể cưỡng bức hai mép
      không thật sự trùng nhau thành một topology kín, làm sai thể tích.
    - RebuildEdges cũng không được dùng để "che" khe hình học; bản chất
      lệnh đó là khôi phục edge về underlying surface.
    """
    if not raw_breps:
        return None

    old_redraw = rs.EnableRedraw(False)
    previous_selection = list(rs.SelectedObjects() or [])
    before_ids = set(rs.AllObjects() or [])
    input_ids = []

    try:
        # ------------------------------------------------------------
        # Tạo các Brep tạm đúng từ geometry mà code vừa sinh.
        # ------------------------------------------------------------
        for brep in raw_breps:
            if brep is None:
                continue

            try:
                duplicate = brep.DuplicateBrep()
                object_id = sc.doc.Objects.AddBrep(
                    duplicate
                )
            except Exception:
                object_id = System.Guid.Empty

            if (
                object_id is not None and
                object_id != System.Guid.Empty
            ):
                input_ids.append(object_id)

        if not input_ids:
            return None

        # ------------------------------------------------------------
        # BƯỚC A - CreateSolid:
        # Rhino tự tìm các vùng kín được bao bởi surface/polysurface.
        # Đây là lệnh phù hợp hơn Join khi các surface có giao/overlap.
        # ------------------------------------------------------------
        rs.UnselectAllObjects()
        rs.SelectObjects(input_ids)

        print(
            "Hydro Rhino Native V7.8 | CreateSolid | input=%d" %
            len(input_ids)
        )

        try:
            rs.Command(
                "_CreateSolid",
                echo=False
            )
        except Exception as command_error:
            print(
                "CreateSolid command exception: %s" %
                str(command_error)
            )

        candidate_ids = hydro_native_temp_ids_since(
            before_ids,
            input_ids
        )

        solid = hydro_native_largest_solid_from_ids(
            candidate_ids
        )

        if solid is not None:
            print(
                "Hydro Rhino Native V7.8 | CreateSolid SUCCESS"
            )
            return solid

        # ------------------------------------------------------------
        # BƯỚC B - Join:
        # Nếu CreateSolid chưa thành công, cho Rhino tự Join các mặt.
        # ------------------------------------------------------------
        existing_inputs = [
            object_id
            for object_id in input_ids
            if rs.IsObject(object_id)
        ]

        if existing_inputs:
            rs.UnselectAllObjects()
            rs.SelectObjects(existing_inputs)

            print(
                "Hydro Rhino Native V7.8 | Join"
            )

            try:
                rs.Command(
                    "_Join",
                    echo=False
                )
            except Exception as command_error:
                print(
                    "Join command exception: %s" %
                    str(command_error)
                )

        candidate_ids = hydro_native_temp_ids_since(
            before_ids,
            input_ids
        )

        # ------------------------------------------------------------
        # BƯỚC C - Cap:
        # Chỉ đóng các lỗ PHẲNG. Nếu deck/transom tạo một loop phẳng hợp lệ,
        # Rhino sẽ đóng chính xác mà không nội suy bừa một mặt cong.
        # ------------------------------------------------------------
        cap_candidates = [
            object_id
            for object_id in candidate_ids
            if rs.IsObject(object_id)
        ]

        if cap_candidates:
            rs.UnselectAllObjects()
            rs.SelectObjects(cap_candidates)

            print(
                "Hydro Rhino Native V7.8 | Cap"
            )

            try:
                rs.Command(
                    "_Cap",
                    echo=False
                )
            except Exception as command_error:
                print(
                    "Cap command exception: %s" %
                    str(command_error)
                )

        candidate_ids = hydro_native_temp_ids_since(
            before_ids,
            input_ids
        )

        solid = hydro_native_largest_solid_from_ids(
            candidate_ids
        )

        if solid is not None:
            print(
                "Hydro Rhino Native V7.8 | Join+Cap SUCCESS"
            )
            return solid

        # ------------------------------------------------------------
               
        # Nếu chưa tạo được solid, KHÔNG bỏ candidate tốt nhất.
        # Trả Brep có số naked edge nhỏ nhất để bước sau tiếp tục
        # tạo mặt đường nước / Cap. Trường hợp thực tế của người dùng
        # đã có candidate chỉ còn 4 naked edges.
        # ------------------------------------------------------------
        best_shell = hydro_native_best_shell_from_ids(
            candidate_ids
        )

        if best_shell is not None:
            print(
                (
                    "Hydro Rhino Native V7.8 | "
                    "return best non-solid shell | naked=%d"
                ) %
                hydro_naked_edge_count(
                    best_shell
                )
            )

            return best_shell

        print(
            "Hydro Rhino Native V7.8 | không có candidate hợp lệ."
        )

        return None

    finally:
        # ------------------------------------------------------------
        # Xóa toàn bộ geometry sinh ra trong chuỗi command.
        # Không xóa bất kỳ object nào có trước khi chạy thủy tĩnh.
        # ------------------------------------------------------------
        current_ids = set(rs.AllObjects() or [])
        delete_ids = list(
            current_ids.difference(
                before_ids
            )
        )

        if delete_ids:
            try:
                rs.DeleteObjects(
                    delete_ids
                )
            except Exception:
                for object_id in delete_ids:
                    try:
                        if rs.IsObject(object_id):
                            rs.DeleteObject(object_id)
                    except Exception:
                        pass

        rs.UnselectAllObjects()

        for object_id in previous_selection:
            try:
                if rs.IsObject(object_id):
                    rs.SelectObject(
                        object_id
                    )
            except Exception:
                pass

        rs.EnableRedraw(
            old_redraw
        )


def hydro_largest_solid_brep(breps):
    """Chọn solid có thể tích lớn nhất trong danh sách Brep."""
    if not breps:
        return None
    best_brep = None
    best_volume = -1.0
    for brep in breps:
        if brep is None:
            continue
        candidate = brep
        if not candidate.IsSolid:
            for factor in (2.0, 5.0, 10.0, 20.0):
                try:
                    capped = candidate.CapPlanarHoles(
                        sc.doc.ModelAbsoluteTolerance * factor
                    )
                    if capped is not None:
                        candidate = capped
                    if candidate.IsSolid:
                        break
                except Exception:
                    pass
        if not candidate.IsSolid:
            continue
        try:
            props = rg.VolumeMassProperties.Compute(candidate)
        except Exception:
            props = None
        if props is None:
            continue
        volume = abs(float(props.Volume))
        if volume > best_volume:
            best_volume = volume
            best_brep = candidate
    return best_brep


def hydro_choose_largest_shell(breps):
    """Chọn cụm Brep lớn nhất; shell không bắt buộc phải kín ở boong."""
    if not breps:
        return None
    best = None
    best_area = -1.0
    for brep in breps:
        if brep is None:
            continue
        area = hydro_brep_area(brep)
        if area > best_area:
            best_area = area
            best = brep
    return best



def hydro_auto_join_naked_edges(brep):
    """
    TỰ ĐỘNG HÓA QUY TRÌNH SHOWEDGES -> JOINEDGE.

    RhinoCommon có Brep.JoinNakedEdges(tolerance), tương đương về mục đích
    với việc người dùng:
        ShowEdges -> tìm naked edges -> JoinEdge các cặp cạnh gần/trùng nhau.

    Hàm chỉ chạy trên BẢN SAO TẠM dùng cho thủy tĩnh, tuyệt đối không sửa
    polysurface của Chế độ 1.

    Cách làm:
    1. Duplicate Brep.
    2. Đếm naked edge ban đầu.
    3. Thử JoinNakedEdges theo nhiều mức dung sai tăng dần.
    4. Chỉ giữ kết quả nếu số naked edge giảm hoặc Brep trở thành solid.
    5. Thử CapPlanarHoles sau mỗi giai đoạn.
    """
    if brep is None:
        return None

    candidate = brep.DuplicateBrep()

    base_tol = max(
        float(sc.doc.ModelAbsoluteTolerance),
        1.0e-6
    )

    # Mô hình dùng mm.
    # Các mức cuối 3 và 5 mm chỉ là "cứu hộ" cho bản tính thủy tĩnh tạm.
    # Nếu cần tới mức này, Output sẽ ghi rõ để người dùng biết.
    tolerance_values = [
        base_tol,
        base_tol * 2.0,
        base_tol * 5.0,
        base_tol * 10.0,
        model_units_from_mm(0.25, GeometryUnitsPerMeter),
        model_units_from_mm(0.50, GeometryUnitsPerMeter),
        model_units_from_mm(1.00, GeometryUnitsPerMeter),
        model_units_from_mm(2.00, GeometryUnitsPerMeter),
        model_units_from_mm(3.00, GeometryUnitsPerMeter),
        model_units_from_mm(5.00, GeometryUnitsPerMeter)
    ]

    unique_tolerances = []

    for value in tolerance_values:
        value = max(
            base_tol,
            float(value)
        )

        # Không lặp lại các mức gần như giống nhau.
        duplicate = False

        for old_value in unique_tolerances:
            if abs(value - old_value) <= 1.0e-9:
                duplicate = True
                break

        if not duplicate:
            unique_tolerances.append(
                value
            )

    naked_before = hydro_naked_edge_count(
        candidate
    )

    print(
        "Hydro AutoJoinEdge V7.8 | naked ban dau=%d" %
        naked_before
    )

    best = candidate.DuplicateBrep()
    best_naked = naked_before

    # Nếu đã kín ngay từ đầu thì trả về luôn.
    if candidate.IsSolid:
        return candidate

    for tolerance in unique_tolerances:
        trial = best.DuplicateBrep()

        joins_made = 0

        try:
            # RhinoCommon: tự tìm các cặp naked edge chồng lấn trong tolerance.
            joins_made = int(
                trial.JoinNakedEdges(
                    float(tolerance)
                )
            )
        except Exception as error:
            print(
                "Hydro AutoJoinEdge V7.8 | tol=%.3f | exception=%s" %
                (
                    float(tolerance),
                    str(error)
                )
            )

            continue

        try:
            trial.Compact()
        except Exception:
            pass

        # Sau khi nối cạnh, thử đóng các lỗ phẳng còn lại.
        if not trial.IsSolid:
            try:
                capped = trial.CapPlanarHoles(
                    max(
                        base_tol * 2.0,
                        float(tolerance)
                    )
                )

                if capped is not None:
                    trial = capped
            except Exception:
                pass

        naked_after = hydro_naked_edge_count(
            trial
        )

        print(
            (
                "Hydro AutoJoinEdge V7.8 | tol=%.3f mm | "
                "joins=%d | naked: %d -> %d | solid=%s"
            ) % (
                float(tolerance),
                joins_made,
                best_naked,
                naked_after,
                str(trial.IsSolid)
            )
        )

        # Chỉ nhận bước sửa nếu topology tốt lên.
        if (
            trial.IsSolid or
            naked_after < best_naked
        ):
            best = trial
            best_naked = naked_after

        if best.IsSolid or best_naked == 0:
            break

    print(
        (
            "Hydro AutoJoinEdge V7.8 | ket qua | "
            "naked=%d | solid=%s"
        ) % (
            best_naked,
            str(best.IsSolid)
        )
    )

    return best


def hydro_join_open_shell(raw_breps, joined_breps):
    """
    Join các mặt vỏ thành shell liên tục nhưng KHÔNG yêu cầu đóng boong.
    Đây là thay đổi chính của V7.1: phần chìm sẽ được đóng kín sau khi cắt
    đúng tại mớn nước, thay vì bắt toàn bộ vỏ tàu phải là solid trước.
    """
    source_breps = []
    if raw_breps:
        source_breps = [b for b in raw_breps if b is not None]
    elif joined_breps:
        source_breps = [b for b in joined_breps if b is not None]
    if not source_breps:
        return None

    base_tol = max(float(sc.doc.ModelAbsoluteTolerance), 1.0e-6)
    raw_tolerances = [
        base_tol * 2.0,
        base_tol * 5.0,
        base_tol * 10.0,
        base_tol * 20.0,
        base_tol * 50.0,
        base_tol * 100.0,
        base_tol * 200.0
    ]

    # Đơn vị mô hình là mm. Không cho tolerance vượt 2 mm để tránh nối nhầm.
    tolerances = []
    for value in raw_tolerances:
        safe_value = min(float(value), 2.0)
        if safe_value not in tolerances:
            tolerances.append(safe_value)

    best_shell = None
    best_area = -1.0
    best_naked = 999999

    for tolerance in tolerances:
        try:
            joined = rg.Brep.JoinBreps(source_breps, tolerance)
        except Exception:
            joined = None
        if not joined:
            print(
                "Hydro Join V7.6-Legacy | tol=%.6f | join failed" %
                float(tolerance)
            )
            continue

        candidate = hydro_choose_largest_shell(joined)
        if candidate is None:
            print(
                "Hydro Join V7.6-Legacy | tol=%.6f | no candidate" %
                float(tolerance)
            )
            continue

        # --------------------------------------------------------------
               
        # Sau Join thông thường, tự động xử lý naked edges giống thao tác
        # ShowEdges -> JoinEdge mà người dùng đang làm thủ công trong Rhino.
        # --------------------------------------------------------------
        repaired_candidate = hydro_auto_join_naked_edges(
            candidate
        )

        if repaired_candidate is not None:
            candidate = repaired_candidate

        area = hydro_brep_area(candidate)
        naked = hydro_naked_edge_count(candidate)

        print(
            "Hydro Join V7.6-Legacy | tol=%.6f | components=%d | naked=%d | area=%.3f" %
            (
                float(tolerance),
                len(joined),
                naked,
                area
            )
        )
        if (
            area > best_area * 1.000001 or
            (abs(area - best_area) <= max(1.0, best_area) * 1.0e-6 and naked < best_naked)
        ):
            best_shell = candidate
            best_area = area
            best_naked = naked

    if best_shell is None:
        best_shell = hydro_choose_largest_shell(joined_breps)

    if best_shell is not None:
        print(
            "Hydro shell V7.6-Legacy | IsSolid=%s | naked edges=%d | area=%.3f" %
            (str(best_shell.IsSolid), hydro_naked_edge_count(best_shell), hydro_brep_area(best_shell))
        )
    return best_shell



class HydroSurfaceSource(object):
    """
    Nguồn hình học cho thủy tĩnh dạng SURFACE.

    Không yêu cầu:
    - Join kín;
    - IsSolid;
    - BooleanIntersection.

    Dữ liệu chính:
    - raw_breps: các mặt vỏ + vách đuôi đúng theo Chế độ 1.
    - mesh_triangles: cache tam giác hóa toàn bộ các mặt để tính nhiều mớn nước.
    """
    def __init__(self, raw_breps, hull_line_geometry_records=None,
                 linesplan_brep_count=None, construction_warnings=None):
        self.raw_breps = [
            brep.DuplicateBrep()
            for brep in (raw_breps or [])
            if brep is not None
        ]

        if linesplan_brep_count is None:
            linesplan_brep_count = len(self.raw_breps)
        self.linesplan_breps = self.raw_breps[:max(
            0, min(int(linesplan_brep_count), len(self.raw_breps)))]
        self.mesh_triangles = None
        self.mesh_triangle_count = 0
        self.mesh_failures = []
        self.mesh_fallbacks = []
        self.construction_warnings = list(construction_warnings or [])
        self.hull_line_geometry_records = list(
            hull_line_geometry_records or []
        )




def create_hydrostatic_closed_hull(
    base_params,
    include_hull_lines=False,
    respect_half_model=False
):
    """
    CHUẨN BỊ SURFACE CHO TÍCH PHÂN THỦY TĨNH.

    Khác hoàn toàn các phiên bản trước:
    - Không ép thân tàu thành closed Brep.
    - Không thay topology của tàu để phục vụ Join.
    - Không dùng deck tạm.
    - Không dùng Boolean để lấy phần chìm.

    Chương trình dựng đúng các mặt theo cấu hình hiện tại của Chế độ 1,
    rồi giữ chúng trong bộ nhớ để mesh + cắt tam giác tại từng mớn nước.
    """
            
    # Chế độ 3 dùng chung bộ kiểm tra Units của V19.
    ensure_document_units_match_parameters(
        base_params,
        u"tính thủy tĩnh"
    )

    hydro_params = copy.deepcopy(
        base_params
    )

    # Không tạo các đối tượng phụ trong Rhino.
    hydro_params.show_keel_curve = False
    hydro_params.show_chine_curves = False
    hydro_params.show_sheer_curve = False
    hydro_params.show_longitudinal_curves = False
    hydro_params.show_body_stations = False
    hydro_params.show_bow_fairing_sections = False
    hydro_params.show_design_points = False
    hydro_params.show_transom_frame = False
    hydro_params.create_design_waterline = False

    # Mode 2 lấy đúng nửa mạn đã chọn để tạo SOURCE_3D/Make2D.
    # Mode 3 giữ mặc định toàn thân để thể tích chiếm nước không bị chia đôi.
    hydro_params.create_half_model = (
        bool(getattr(base_params, "create_half_model", False))
        if respect_half_model else False
    )

    # Giữ đúng các mặt vật lý của vỏ.
    hydro_params.create_hull_surfaces = True
    hydro_params.create_transom_surfaces = True
    hydro_params.create_deck_surface = False

           
    # giữ topology y như Chế độ 1 để thể tích tính đúng hình đang thiết kế.
            
    # giữ cùng topology với vỏ hiển thị: một bottom liên tục mỗi bên.
    hydro_params.split_bottom_at_keel_stem = False
    hydro_params.split_side_panels_at_bow = (
        base_params.split_side_panels_at_bow
    )
    hydro_params.use_longitudinal_rail_surfaces = (
        base_params.use_longitudinal_rail_surfaces
    )

    # Không cần Join vì engine mới không dựa vào topology Join.
    hydro_params.join_hull_surfaces = False
    hydro_params.add_individual_surfaces_when_join_fails = False

    hydro_params.export_parameter_table = False
    hydro_params.export_station_table = False

    temp_ids = []

    try:
        result = generate_hull(
            hydro_params,
            register_linesplan_sources=bool(include_hull_lines)
        )

        temp_ids = list(
            result.get(
                "object_ids",
                []
            )
        )

        raw_breps = result.get(
            "hull_breps",
            None
        )

        if not raw_breps:
            raise Exception(
                u"Không tạo được các mặt vỏ để tính thủy tĩnh."
            )

        surface_report = list(result.get("surface_report", []))
        construction_warnings = []
        if "Transom panel 0: planar" not in surface_report:
            construction_warnings.append(
                u"thiếu mặt vách đuôi dưới (Transom panel 0)"
            )
            Rhino.RhinoApp.WriteLine(
                "Model 112 hydro warning: Transom panel 0 missing"
            )

        print(
            "Hydro | surface source=%d Brep | không yêu cầu IsSolid" %
            len(raw_breps)
        )

        # Duplicate the same-run features, including the Transom, before
        # generate_hull temporary objects are deleted in finally.
        line_geometry_records = []
        if include_hull_lines:
            for record in result.get(
                "hull_line_data", {}
            ).get("records", []):
                captured = []
                for object_id in record.get("all_ids", []):
                    try:
                        rhino_object = sc.doc.Objects.FindId(object_id)
                        geometry = rhino_object.Geometry if rhino_object else None
                    except Exception:
                        geometry = None
                    if isinstance(geometry, rg.Curve):
                        captured.append(
                            (object_id, geometry.DuplicateCurve())
                        )
                if captured:
                    copied_record = dict(record)
                    copied_record["curve_geometries"] = captured
                    line_geometry_records.append(copied_record)

        return HydroSurfaceSource(
            raw_breps,
            line_geometry_records,
            result.get("linesplan_brep_count", len(raw_breps)),
            construction_warnings
        )

    finally:
        delete_object_ids(
            temp_ids
        )

        apply_parameter_bindings(
            copy.deepcopy(
                base_params
            )
        )



def create_hydro_water_box(base_params, draft_mm):
    """Tạo hộp nước lớn, dùng khi shell đầu vào tình cờ đã là solid."""
    L_local = float(base_params.length)
    B_local = float(base_params.beam)
    H_local = float(base_params.depth)
    z0 = float(base_params.baseline_z)
    water_z = z0 + float(draft_mm)
    margin_x = max(2000.0, L_local * 0.25)
    margin_y = max(2000.0, B_local * 0.75)
    margin_z = max(2000.0, H_local * 1.50)
    box = rg.Box(
        rg.Plane.WorldXY,
        rg.Interval(-margin_x, L_local + margin_x),
        rg.Interval(-B_local - margin_y, B_local + margin_y),
        rg.Interval(z0 - margin_z, water_z)
    )
    return box.ToBrep()


def create_hydro_waterplane_cutter(base_params, draft_mm):
    """Tạo mặt phẳng Brep rất lớn tại Z = mớn nước."""
    L_local = float(base_params.length)
    B_local = float(base_params.beam)
    water_z = float(base_params.baseline_z) + float(draft_mm)
    margin_x = max(3000.0, L_local * 0.35)
    margin_y = max(3000.0, B_local * 1.25)
    plane = rg.Plane(rg.Point3d(0.0, 0.0, water_z), rg.Vector3d.ZAxis)
    surface = rg.PlaneSurface(
        plane,
        rg.Interval(-margin_x, L_local + margin_x),
        rg.Interval(-B_local - margin_y, B_local + margin_y)
    )
    return plane, surface.ToBrep()


def hydro_cap_underwater_piece(piece, water_z):
    """Cap mặt đường nước của một mảnh shell nằm hoàn toàn dưới Z = water_z."""
    if piece is None:
        return None
    base_tol = max(float(sc.doc.ModelAbsoluteTolerance), 1.0e-6)
    try:
        bbox = piece.GetBoundingBox(True)
    except Exception:
        bbox = None
    if bbox is None:
        return None
    z_allow = max(base_tol * 20.0, 0.10)
    if float(bbox.Min.Z) >= water_z - z_allow:
        return None
    if float(bbox.Max.Z) > water_z + z_allow:
        return None
    if piece.IsSolid:
        return piece
    for factor in (2.0, 5.0, 10.0, 20.0, 50.0):
        try:
            capped = piece.CapPlanarHoles(base_tol * factor)
        except Exception:
            capped = None
        if capped is not None and capped.IsSolid:
            return capped
    return None



HYDRO_DIAGNOSTIC_LAYER = u"kiểm tra thủy tĩnh - mép hở dưới nước"
HYDRO_WATERLINE_DIAGNOSTIC_LAYER = u"kiểm tra thủy tĩnh - biên đường nước"


def hydro_piece_bbox(brep):
    if brep is None:
        return None

    try:
        return brep.GetBoundingBox(
            True
        )
    except Exception:
        return None


def hydro_piece_is_below_water(brep, water_z, tolerance):
    """
    Phân loại một mảnh Brep sau Split.

    Chấp nhận mảnh có phần lớn hình học nằm dưới water_z.
    """
    bbox = hydro_piece_bbox(
        brep
    )

    if bbox is None:
        return False

    z_min = float(
        bbox.Min.Z
    )

    z_max = float(
        bbox.Max.Z
    )

    # Hoàn toàn phía trên -> loại.
    if z_min >= water_z - tolerance:
        return False

    # Hoàn toàn dưới -> giữ.
    if z_max <= water_z + tolerance:
        return True

    # Trường hợp rất sát mặt cắt:
    # dùng tâm bbox để quyết định.
    z_mid = 0.5 * (
        z_min +
        z_max
    )

    return z_mid < water_z


def hydro_split_one_surface_below_water(
    brep,
    cutter_brep,
    water_z,
    base_tolerance
):
    """
    Cắt MỘT Brep rời tại mặt đường nước và chỉ trả các phần bên dưới.

    Đây là khác biệt quyết định so với V7.5:
    cạnh hở phía sheer/boong bị loại ngay ở bước này, trước khi Join.
    """
    if brep is None:
        return []

    bbox = hydro_piece_bbox(
        brep
    )

    if bbox is None:
        return []

    # Mặt hoàn toàn dưới nước -> giữ nguyên.
    if float(bbox.Max.Z) <= water_z + base_tolerance:
        return [
            brep.DuplicateBrep()
        ]

    # Mặt hoàn toàn trên nước -> bỏ.
    if float(bbox.Min.Z) >= water_z - base_tolerance:
        return []

    # Mặt cắt qua đường nước -> Split.
    tolerance_values = [
        base_tolerance,
        base_tolerance * 2.0,
        base_tolerance * 5.0,
        base_tolerance * 10.0,
        0.25,
        0.50,
        1.00
    ]

    for tolerance in tolerance_values:
        tolerance = max(
            base_tolerance,
            float(tolerance)
        )

        pieces = None

        try:
            pieces = brep.Split(
                cutter_brep,
                tolerance
            )
        except Exception:
            pieces = None

        if not pieces:
            continue

        below = []

        for piece in pieces:
            if hydro_piece_is_below_water(
                piece,
                water_z,
                max(tolerance, 0.10)
            ):
                below.append(
                    piece.DuplicateBrep()
                )

        if below:
            return below

    # Nếu Split thất bại nhưng bbox chỉ vượt mặt nước rất nhỏ,
    # giữ lại để Join/Cap xử lý. Không dùng cho trường hợp vượt lớn.
    overshoot = (
        float(bbox.Max.Z) -
        float(water_z)
    )

    if overshoot <= max(
        base_tolerance * 20.0,
        0.50
    ):
        return [
            brep.DuplicateBrep()
        ]

    print(
        "Hydro | Split surface failed | z=[%.3f, %.3f] | water=%.3f" %
        (
            float(bbox.Min.Z),
            float(bbox.Max.Z),
            float(water_z)
        )
    )

    return []



def hydro_curve_bbox(curve):
    if curve is None:
        return None

    try:
        return curve.GetBoundingBox(
            True
        )
    except Exception:
        return None


def hydro_is_edge_on_waterplane(
    curve,
    water_z,
    tolerance
):
    """
    Kiểm tra một naked edge có nằm trên mặt phẳng Z = water_z hay không.

    Không chỉ kiểm tra endpoint mà kiểm tra bounding box của toàn curve.
    """
    bbox = hydro_curve_bbox(
        curve
    )

    if bbox is None:
        return False

    return (
        abs(float(bbox.Min.Z) - float(water_z)) <= tolerance and
        abs(float(bbox.Max.Z) - float(water_z)) <= tolerance
    )


def hydro_classify_naked_edges(
    brep,
    water_z
):
    """
    Chia naked edges thành:
    - water_edges: biên cắt nằm trên mặt đường nước.
    - below_edges: cạnh hở thật nằm dưới/khác mặt đường nước.

    Đây là bước chẩn đoán quan trọng của V7.7.
    """
    if brep is None:
        return [], []

    try:
        naked_edges = brep.DuplicateNakedEdgeCurves(
            True,
            True
        )
    except Exception:
        naked_edges = None

    if not naked_edges:
        return [], []

    tolerance = max(
        float(sc.doc.ModelAbsoluteTolerance) * 20.0,
        0.50
    )

    water_edges = []
    below_edges = []

    for curve in naked_edges:
        if hydro_is_edge_on_waterplane(
            curve,
            water_z,
            tolerance
        ):
            water_edges.append(
                curve
            )
        else:
            below_edges.append(
                curve
            )

    print(
        (
            "Hydro edge classify | total=%d | "
            "waterplane=%d | below/other=%d"
        ) % (
            len(naked_edges),
            len(water_edges),
            len(below_edges)
        )
    )

    return (
        water_edges,
        below_edges
    )


def hydro_create_waterplane_caps_from_edges(
    water_edges,
    water_z
):
    """
    Nối các cạnh cắt tại Z=T thành loop kín rồi tạo Planar Brep.

    Thay vì trông chờ CapPlanarHoles tự nhận ra một đường bao gồm nhiều
    Brep edge nhỏ, V7.7 tạo mặt đường nước một cách tường minh.
    """
    if not water_edges:
        return []

    base_tol = max(
        float(sc.doc.ModelAbsoluteTolerance),
        1.0e-6
    )

    tolerance_values = [
        base_tol * 2.0,
        base_tol * 5.0,
        base_tol * 10.0,
        model_units_from_mm(0.25, GeometryUnitsPerMeter),
        model_units_from_mm(0.50, GeometryUnitsPerMeter),
        model_units_from_mm(1.00, GeometryUnitsPerMeter),
        model_units_from_mm(2.00, GeometryUnitsPerMeter),
        model_units_from_mm(3.00, GeometryUnitsPerMeter),
        model_units_from_mm(5.00, GeometryUnitsPerMeter)
    ]

    best_closed_loops = []

    for tolerance in tolerance_values:
        tolerance = max(
            base_tol,
            float(tolerance)
        )

        try:
            joined_curves = rg.Curve.JoinCurves(
                water_edges,
                tolerance
            )
        except Exception:
            joined_curves = None

        if not joined_curves:
            continue

        closed_loops = []

        for curve in joined_curves:
            if curve is None:
                continue

            try:
                is_closed = bool(
                    curve.IsClosed
                )
            except Exception:
                is_closed = False

            if is_closed:
                closed_loops.append(
                    curve
                )

        print(
            (
                "Hydro water loop | tol=%.3f | "
                "joined=%d | closed=%d"
            ) % (
                tolerance,
                len(joined_curves),
                len(closed_loops)
            )
        )

        if len(closed_loops) > len(best_closed_loops):
            best_closed_loops = [
                curve.DuplicateCurve()
                for curve in closed_loops
            ]

        # Một thân tàu thông thường tại một mớn nước cần tối thiểu
        # một loop kín ngoài. Nếu đã có thì thử tạo mặt ngay.
        if closed_loops:
            try:
                caps = rg.Brep.CreatePlanarBreps(
                    closed_loops,
                    tolerance
                )
            except Exception:
                caps = None

            if caps and len(caps) > 0:
                valid_caps = []

                for cap in caps:
                    if cap is not None and cap.IsValid:
                        valid_caps.append(
                            cap
                        )

                if valid_caps:
                    print(
                        "Hydro explicit waterplane caps=%d" %
                        len(valid_caps)
                    )
                    return valid_caps

    # Fallback: thử CreatePlanarBreps trên loop kín tốt nhất.
    if best_closed_loops:
        for tolerance in (
            0.50,
            1.00,
            2.00,
            5.00
        ):
            try:
                caps = rg.Brep.CreatePlanarBreps(
                    best_closed_loops,
                    tolerance
                )
            except Exception:
                caps = None

            if caps and len(caps) > 0:
                return [
                    cap
                    for cap in caps
                    if cap is not None
                ]

    return []


def hydro_join_candidate_with_explicit_waterplane(
    candidate,
    water_z
):
    """
    Đóng candidate bằng mặt đường nước tạo tường minh.

    Trả:
        repaired_candidate,
        water_edge_count,
        below_edge_count
    """
    if candidate is None:
        return None, 0, 0

    water_edges, below_edges = hydro_classify_naked_edges(
        candidate,
        water_z
    )

    # Nếu không có biên đường nước thì không có gì để tạo cap.
    if not water_edges:
        return (
            candidate,
            0,
            len(below_edges)
        )

    caps = hydro_create_waterplane_caps_from_edges(
        water_edges,
        water_z
    )

    if not caps:
        print(
            "Hydro | không tạo được explicit waterplane cap."
        )

        return (
            candidate,
            len(water_edges),
            len(below_edges)
        )

    pieces_to_join = [
        candidate
    ]

    pieces_to_join.extend(
        caps
    )

    base_tol = max(
        float(sc.doc.ModelAbsoluteTolerance),
        1.0e-6
    )

    for tolerance in (
        base_tol * 2.0,
        base_tol * 5.0,
        base_tol * 10.0,
        model_units_from_mm(0.25, GeometryUnitsPerMeter),
        model_units_from_mm(0.50, GeometryUnitsPerMeter),
        model_units_from_mm(1.00, GeometryUnitsPerMeter),
        model_units_from_mm(2.00, GeometryUnitsPerMeter),
        model_units_from_mm(3.00, GeometryUnitsPerMeter),
        model_units_from_mm(5.00, GeometryUnitsPerMeter)
    ):
        tolerance = max(
            base_tol,
            float(tolerance)
        )

        try:
            joined = rg.Brep.JoinBreps(
                pieces_to_join,
                tolerance
            )
        except Exception:
            joined = None

        if not joined:
            continue

        joined_candidate = hydro_choose_largest_shell(
            joined
        )

        if joined_candidate is None:
            continue

        # Dọn sai số cực nhỏ sau khi đã có cap thật.
        repaired = hydro_auto_join_naked_edges(
            joined_candidate
        )

        if repaired is not None:
            joined_candidate = repaired

        naked = hydro_naked_edge_count(
            joined_candidate
        )

        print(
            (
                "Hydro cap join | tol=%.3f | "
                "components=%d | naked=%d | solid=%s"
            ) % (
                tolerance,
                len(joined),
                naked,
                str(joined_candidate.IsSolid)
            )
        )

        if joined_candidate.IsSolid:
            return (
                joined_candidate,
                len(water_edges),
                len(below_edges)
            )

        # Nếu không solid nhưng naked giảm, vẫn giữ candidate tốt hơn.
        if naked < hydro_naked_edge_count(candidate):
            candidate = joined_candidate

    return (
        candidate,
        len(water_edges),
        len(below_edges)
    )



def hydro_join_underwater_patches(
    underwater_patches,
    water_z
):
    """
    Join toàn bộ các mảnh đã được cắt dưới đường nước.

    Sau Join:
    - AutoJoinEdge chỉ xử lý sai số mép nhỏ.
    - CapPlanarHoles đóng đúng mặt đường nước.
    - Nếu Rhino native CreateSolid giúp được thì dùng làm fallback.
    """
    if not underwater_patches:
        return None

    base_tol = max(
        float(sc.doc.ModelAbsoluteTolerance),
        1.0e-6
    )

    tolerance_values = [
        base_tol * 2.0,
        base_tol * 5.0,
        base_tol * 10.0,
        model_units_from_mm(0.25, GeometryUnitsPerMeter),
        model_units_from_mm(0.50, GeometryUnitsPerMeter),
        model_units_from_mm(1.00, GeometryUnitsPerMeter),
        model_units_from_mm(2.00, GeometryUnitsPerMeter),
        model_units_from_mm(3.00, GeometryUnitsPerMeter),
        model_units_from_mm(5.00, GeometryUnitsPerMeter)
    ]

    best_candidate = None
    best_naked = 999999

    for tolerance in tolerance_values:
        tolerance = max(
            base_tol,
            float(tolerance)
        )

        try:
            joined = rg.Brep.JoinBreps(
                underwater_patches,
                tolerance
            )
        except Exception:
            joined = None

        if not joined:
            continue

        print(
            "Hydro CutFirst Join | tol=%.3f | components=%d" %
            (
                tolerance,
                len(joined)
            )
        )

        # Thử từng component vì đôi khi Join tạo vài cụm.
        for component in joined:
            if component is None:
                continue

            candidate = component.DuplicateBrep()

            repaired = hydro_auto_join_naked_edges(
                candidate
            )

            if repaired is not None:
                candidate = repaired

            # ----------------------------------------------------------
                   
            # Tách riêng các naked edge nằm đúng tại Z=T và dựng hẳn
            # PlanarSrf mặt đường nước từ các loop này.
            # ----------------------------------------------------------
            if not candidate.IsSolid:
                (
                    candidate,
                    water_edge_count,
                    below_edge_count
                ) = hydro_join_candidate_with_explicit_waterplane(
                    candidate,
                    water_z
                )

                print(
                    (
                        "Hydro after explicit cap | "
                        "water edges=%d | below edges=%d | naked=%d"
                    ) % (
                        water_edge_count,
                        below_edge_count,
                        hydro_naked_edge_count(candidate)
                    )
                )

            # Fallback cuối: đóng các lỗ phẳng còn lại.
            if not candidate.IsSolid:
                for cap_tol in (
                    tolerance,
                    max(tolerance, 0.50),
                    max(tolerance, 1.00),
                    max(tolerance, 2.00),
                    max(tolerance, 5.00)
                ):
                    try:
                        capped = candidate.CapPlanarHoles(
                            cap_tol
                        )
                    except Exception:
                        capped = None

                    if capped is not None:
                        candidate = capped

                    if candidate.IsSolid:
                        break

            naked = hydro_naked_edge_count(
                candidate
            )

            print(
                (
                    "Hydro CutFirst candidate | "
                    "naked=%d | solid=%s"
                ) % (
                    naked,
                    str(candidate.IsSolid)
                )
            )

            if candidate.IsSolid:
                return candidate

            if naked < best_naked:
                best_naked = naked
                best_candidate = candidate.DuplicateBrep()

    # Rhino native fallback trên chính các PATCH ĐÃ CẮT.
                                                                          
    native_candidate = hydro_try_rhino_native_solid(
        underwater_patches
    )

    if native_candidate is not None:
        native_naked = hydro_naked_edge_count(
            native_candidate
        )

        print(
            (
                "Hydro native candidate | "
                "solid=%s | naked=%d"
            ) % (
                str(native_candidate.IsSolid),
                native_naked
            )
        )

        if native_candidate.IsSolid:
            return native_candidate

        # Tạo explicit waterplane trên candidate tốt nhất do Rhino Join tạo.
        (
            native_candidate,
            native_water_edges,
            native_below_edges
        ) = hydro_join_candidate_with_explicit_waterplane(
            native_candidate,
            water_z
        )

        native_naked = hydro_naked_edge_count(
            native_candidate
        )

        print(
            (
                "Hydro native after water cap | "
                "water=%d | below=%d | naked=%d | solid=%s"
            ) % (
                native_water_edges,
                native_below_edges,
                native_naked,
                str(native_candidate.IsSolid)
            )
        )

        # Thử CapPlanarHoles cuối trên candidate chỉ còn rất ít edge.
        if not native_candidate.IsSolid:
            for cap_tol in (
                0.25,
                0.50,
                1.00,
                2.00,
                3.00,
                5.00
            ):
                try:
                    capped = native_candidate.CapPlanarHoles(
                        cap_tol
                    )
                except Exception:
                    capped = None

                if capped is not None:
                    native_candidate = capped

                if native_candidate.IsSolid:
                    break

        native_naked = hydro_naked_edge_count(
            native_candidate
        )

        if native_candidate.IsSolid:
            print(
                "Hydro SUCCESS từ Rhino native candidate."
            )
            return native_candidate

        # Dù chưa solid, nếu native candidate tốt hơn candidate cũ,
        # phải giữ nó thay vì quay lại shell nhiều naked edges hơn.
        if (
            best_candidate is None or
            native_naked < best_naked
        ):
            best_candidate = native_candidate.DuplicateBrep()
            best_naked = native_naked

    if best_candidate is not None:
        print(
            "Hydro | best naked after all repair=%d" %
            best_naked
        )

    return best_candidate


def hydro_clear_diagnostic_edges():
    """Xóa các đường chẩn đoán thủy tĩnh cũ nếu có."""
    try:
        layer_index = sc.doc.Layers.FindByFullPath(
            HYDRO_DIAGNOSTIC_LAYER,
            -1
        )
    except Exception:
        layer_index = -1

    if layer_index < 0:
        return

    ids = []

    for obj in sc.doc.Objects:
        try:
            if obj.Attributes.LayerIndex == layer_index:
                ids.append(
                    obj.Id
                )
        except Exception:
            pass

    delete_object_ids(
        ids
    )


def hydro_show_naked_edges_for_diagnosis(
    brep,
    water_z=None
):
    """
    Vẽ riêng:
    - biên mặt đường nước;
    - mép hở thật dưới/khác mặt đường nước.
    """
    hydro_clear_diagnostic_edges()

    if brep is None:
        return 0

    if water_z is None:
        try:
            curves = brep.DuplicateNakedEdgeCurves(
                True,
                True
            )
        except Exception:
            curves = None

        water_edges = []
        below_edges = list(
            curves or []
        )
    else:
        (
            water_edges,
            below_edges
        ) = hydro_classify_naked_edges(
            brep,
            water_z
        )

    def add_curves_to_named_layer(
        curves,
        layer_name
    ):
        if not curves:
            return

        attributes = get_layer_attributes(
            layer_name
        )

        for curve in curves:
            try:
                if attributes is not None:
                    sc.doc.Objects.AddCurve(
                        curve,
                        attributes
                    )
                else:
                    sc.doc.Objects.AddCurve(
                        curve
                    )
            except Exception:
                pass

    add_curves_to_named_layer(
        water_edges,
        HYDRO_WATERLINE_DIAGNOSTIC_LAYER
    )

    add_curves_to_named_layer(
        below_edges,
        HYDRO_DIAGNOSTIC_LAYER
    )

    sc.doc.Views.Redraw()

    print(
        (
            "Hydro diagnostic | waterplane=%d | "
            "below/other=%d"
        ) % (
            len(water_edges),
            len(below_edges)
        )
    )

    return (
        len(water_edges) +
        len(below_edges)
    )



def hydro_build_underwater_from_surface_source(
    source,
    base_params,
    draft_mm
):
    """
    CẮT TRƯỚC, JOIN SAU.
    """
    if source is None or not source.raw_breps:
        return None

    water_z = (
        float(base_params.baseline_z) +
        float(draft_mm)
    )

    base_tol = max(
        float(sc.doc.ModelAbsoluteTolerance) * 2.0,
        1.0e-6
    )

    plane, cutter_brep = create_hydro_waterplane_cutter(
        base_params,
        draft_mm
    )

    underwater_patches = []

    for index, brep in enumerate(
        source.raw_breps
    ):
        pieces = hydro_split_one_surface_below_water(
            brep,
            cutter_brep,
            water_z,
            base_tol
        )

        underwater_patches.extend(
            pieces
        )

    print(
        "Hydro | sau khi cắt T=%.3f m còn %d patch dưới nước." %
        (
            float(draft_mm) /
            float(base_params.units_per_meter),
            len(underwater_patches)
        )
    )

    if not underwater_patches:
        return None

    candidate = hydro_join_underwater_patches(
        underwater_patches,
        water_z
    )

    if candidate is None:
        return None

    # --------------------------------------------------------------
                                                
    # --------------------------------------------------------------
    if not candidate.IsSolid:
        repaired = hydro_auto_join_naked_edges(
            candidate
        )

        if repaired is not None:
            candidate = repaired

    if not candidate.IsSolid:
        (
            candidate,
            final_water_edges,
            final_below_edges
        ) = hydro_join_candidate_with_explicit_waterplane(
            candidate,
            water_z
        )

        print(
            (
                "Hydro final explicit cap | "
                "water=%d | below=%d | naked=%d"
            ) % (
                final_water_edges,
                final_below_edges,
                hydro_naked_edge_count(candidate)
            )
        )

    if not candidate.IsSolid:
        for tolerance in (
            0.25,
            0.50,
            1.00,
            2.00,
            3.00,
            5.00
        ):
            try:
                capped = candidate.CapPlanarHoles(
                    tolerance
                )
            except Exception:
                capped = None

            if capped is not None:
                candidate = capped

            if candidate.IsSolid:
                break

    return candidate



def create_underwater_solid(closed_hull, base_params, draft_mm):
    """
    TẠO SOLID PHẦN CHÌM.

    Nếu nhận HydroSurfaceSource:
        CẮT TỪNG SURFACE TRƯỚC -> JOIN PHẦN CHÌM -> CAP.

    Nếu nhận một Brep solid (trường hợp fallback/phiên bản cũ):
        vẫn dùng Boolean Intersection.
    """
    if closed_hull is None:
        raise Exception(
            u"Không có hình học thân tàu để tính thủy tĩnh."
        )

    # ==============================================================
                                       
    # ==============================================================
    if isinstance(
        closed_hull,
        HydroSurfaceSource
    ):
        underwater = hydro_build_underwater_from_surface_source(
            closed_hull,
            base_params,
            draft_mm
        )

        if underwater is not None and underwater.IsSolid:
            hydro_clear_diagnostic_edges()

            print(
                "Hydro SUCCESS | CutFirst -> Join -> Cap | naked=0"
            )

            return underwater

        naked = hydro_naked_edge_count(
            underwater
        ) if underwater is not None else 999999

        water_count = 0
        below_count = naked

        if underwater is not None:
            (
                water_edges_diag,
                below_edges_diag
            ) = hydro_classify_naked_edges(
                underwater,
                (
                    float(base_params.baseline_z) +
                    float(draft_mm)
                )
            )

            water_count = len(
                water_edges_diag
            )

            below_count = len(
                below_edges_diag
            )

            hydro_show_naked_edges_for_diagnosis(
                underwater,
                (
                    float(base_params.baseline_z) +
                    float(draft_mm)
                )
            )

        raise Exception(
            (
                u"Không khép kín được phần chìm tại T = %.3f m.\n"
                u"Candidate tốt nhất còn %d cạnh hở.\n"
                u"Trong đó: %d cạnh thuộc biên đường nước, %d cạnh là mép hở khác.\n"
                u"giữ lại candidate tốt nhất của Rhino Native thay vì bỏ nó.\n"
                u"Các cạnh còn lại đã được vẽ trên các layer kiểm tra thủy tĩnh."
            ) % (
                float(draft_mm) /
                float(base_params.units_per_meter),
                naked,
                water_count,
                below_count
            )
        )

    # ==============================================================
    # NHÁNH BRE P SOLID CŨ
    # ==============================================================
    water_z = (
        float(base_params.baseline_z) +
        float(draft_mm)
    )

    tolerance = max(
        float(sc.doc.ModelAbsoluteTolerance) * 2.0,
        1.0e-6
    )

    try:
        is_solid = bool(
            closed_hull.IsSolid
        )
    except Exception:
        is_solid = False

    if is_solid:
        water_box = create_hydro_water_box(
            base_params,
            draft_mm
        )

        pieces = None

        try:
            pieces = rg.Brep.CreateBooleanIntersection(
                closed_hull,
                water_box,
                tolerance
            )
        except Exception:
            try:
                pieces = rg.Brep.CreateBooleanIntersection(
                    [closed_hull],
                    [water_box],
                    tolerance
                )
            except Exception:
                pieces = None

        underwater = hydro_largest_solid_brep(
            pieces
        )

        if underwater is not None:
            return underwater

    raise Exception(
        u"Không tạo được thể tích phần chìm từ hình học đầu vào."
    )



def get_waterplane_face_data(underwater_brep, water_z):
    """
    Tìm các mặt phẳng nằm đúng tại cao độ đường nước và tổng hợp các đặc trưng.

    Boolean intersection thường tạo một mặt phẳng đóng phần chìm tại Z = water_z.
    Có thể có hơn một face, vì vậy hàm cộng diện tích và dùng định lý trục song song
    để tổng hợp mô men quán tính quanh trọng tâm toàn mặt đường nước.
    """
    plane_tolerance = max(
        sc.doc.ModelAbsoluteTolerance * 10.0,
        0.10
    )

    face_data = []

    for face in underwater_brep.Faces:
        try:
            face_brep = face.DuplicateFace(False)
            bbox = face_brep.GetBoundingBox(True)
        except Exception:
            continue

        if bbox is None:
            continue

        if (
            abs(float(bbox.Min.Z) - water_z) > plane_tolerance or
            abs(float(bbox.Max.Z) - water_z) > plane_tolerance
        ):
            continue

        props = None
        try:
            props = rg.AreaMassProperties.Compute(face_brep)
        except Exception:
            props = None

        if props is None or float(props.Area) <= 0.0:
            continue

        ix_local = 0.0
        iy_local = 0.0

        try:
            inertia = props.CentroidCoordinatesMomentsOfInertia
            ix_local = float(inertia.X)
            iy_local = float(inertia.Y)
        except Exception:
            # Nếu Rhino không trả được inertia trên phiên bản hiện tại,
            # phần BM/KM sẽ được để trống bằng 0 thay vì làm hỏng toàn bộ phép tính.
            ix_local = 0.0
            iy_local = 0.0

        face_data.append({
            "brep": face_brep,
            "area": float(props.Area),
            "centroid": props.Centroid,
            "ix_local": ix_local,
            "iy_local": iy_local,
            "bbox": bbox
        })

    if not face_data:
        raise Exception(
            u"Không nhận dạng được mặt đường nước sau khi cắt thể tích phần chìm."
        )

    total_area = sum(item["area"] for item in face_data)
    cx = sum(
        item["area"] * float(item["centroid"].X)
        for item in face_data
    ) / total_area
    cy = sum(
        item["area"] * float(item["centroid"].Y)
        for item in face_data
    ) / total_area

    ix_total = 0.0
    iy_total = 0.0

    min_x = None
    max_x = None
    min_y = None
    max_y = None

    for item in face_data:
        area = item["area"]
        centroid = item["centroid"]
        dx = float(centroid.X) - cx
        dy = float(centroid.Y) - cy

        # Trục X là trục dọc tàu -> Ix dùng cho ổn định ngang (roll/BMt).
        ix_total += item["ix_local"] + area * dy * dy
        # Trục Y là trục ngang tàu -> Iy dùng cho ổn định dọc (pitch/BMl).
        iy_total += item["iy_local"] + area * dx * dx

        bbox = item["bbox"]
        bx0 = float(bbox.Min.X)
        bx1 = float(bbox.Max.X)
        by0 = float(bbox.Min.Y)
        by1 = float(bbox.Max.Y)

        min_x = bx0 if min_x is None else min(min_x, bx0)
        max_x = bx1 if max_x is None else max(max_x, bx1)
        min_y = by0 if min_y is None else min(min_y, by0)
        max_y = by1 if max_y is None else max(max_y, by1)

    return {
        "area_mm2": total_area,
        "centroid_x_mm": cx,
        "centroid_y_mm": cy,
        "ix_mm4": ix_total,
        "iy_mm4": iy_total,
        "lwl_mm": max(0.0, max_x - min_x),
        "bwl_mm": max(0.0, max_y - min_y),
        "min_x_mm": min_x,
        "max_x_mm": max_x
    }



# =============================================================================
                                                         
# =============================================================================
# Ý tưởng:
# 1. Mesh từng Brep của vỏ tàu.
# 2. Cắt từng tam giác tại Z = T bằng thuật toán polygon clipping.
# 3. Giữ toàn bộ tam giác phần chìm.
# 4. Từ các cạnh cắt tạo đường bao mặt nước.
# 5. Đóng mặt nước về mặt TOÁN HỌC bằng các tam giác phẳng.
# 6. Tích phân thể tích có dấu qua các tetrahedron tam giác.
#
# Kết quả:
# - Không cần Rhino Brep.IsSolid == True.
# - Naked edge giữa các Brep không còn là điều kiện chặn.
# - Sai số phụ thuộc chủ yếu vào mật độ mesh và độ kín của đường bao mặt nước.
# =============================================================================


def hydro_v79_point3d(vertex):
    """Chuyển Point3f/Point3d thành Point3d."""
    return rg.Point3d(
        float(vertex.X),
        float(vertex.Y),
        float(vertex.Z)
    )


def hydro_v79_distance_xy(point_a, point_b):
    dx = float(point_a.X) - float(point_b.X)
    dy = float(point_a.Y) - float(point_b.Y)

    return math.sqrt(
        dx * dx +
        dy * dy
    )


def hydro_v79_mesh_parameters(base_params):
    """
    Mesh riêng cho thủy tĩnh.

    Bản V9:
    - sửa MinimumEdgeLength theo đơn vị vật lý (mm), tránh lỗi 2 model units
      trở thành 2 m khi tài liệu Rhino dùng Meters;
    - tăng mật độ mesh để V, LCB, KB và S hội tụ gần kết quả NURBS hơn;
    - target edge mặc định khoảng L/320, giới hạn 40-120 mm.

    Với L = 24 m:
        target edge ≈ 75 mm.
    """
    length_model = float(
        base_params.length
    )

    units = float(
        base_params.units_per_meter
    )

    target_edge = max(
        model_units_from_mm(
            40.0,
            units
        ),
        min(
            model_units_from_mm(
                120.0,
                units
            ),
            length_model / 320.0
        )
    )

    # Minimum edge cũng phải theo đơn vị vật lý.
    minimum_edge = max(
        model_units_from_mm(
            1.0,
            units
        ),
        target_edge * 0.02
    )

    minimum_edge = min(
        minimum_edge,
        target_edge * 0.20
    )

    parameters = rg.MeshingParameters()

    try:
        parameters.MaximumEdgeLength = target_edge
    except Exception:
        pass

    try:
        parameters.MinimumEdgeLength = minimum_edge
    except Exception:
        pass

    try:
        parameters.RefineGrid = True
    except Exception:
        pass

    try:
        parameters.JaggedSeams = False
    except Exception:
        pass

    try:
        parameters.SimplePlanes = True
    except Exception:
        pass

    try:
        parameters.GridAmplification = 1.0
    except Exception:
        pass

    # Các thuộc tính dưới đây có thể khác giữa các build Rhino,
    # vì vậy đều đặt trong try.
    try:
        parameters.Tolerance = model_units_from_mm(
            0.10,
            units
        )
    except Exception:
        pass

    try:
        parameters.MaximumAngle = math.radians(
            5.0
        )
    except Exception:
        pass

    return (
        parameters,
        target_edge
    )


def hydro_v79_mesh_source_triangles(
    source,
    base_params
):
    """
    Mesh toàn bộ Brep chỉ MỘT LẦN và cache danh sách tam giác.

    Mỗi phần tử:
        (Point3d p0, Point3d p1, Point3d p2)
    """
    if source.mesh_triangles is not None:
        return source.mesh_triangles

    parameters, target_edge = hydro_v79_mesh_parameters(
        base_params
    )

    triangles = []
    mesh_failures = []
    mesh_fallbacks = []

    for brep_index, brep in enumerate(
        source.raw_breps
    ):
        meshes = None
        triangle_count_before = len(triangles)

        try:
            meshes = rg.Mesh.CreateFromBrep(
                brep,
                parameters
            )
        except Exception as error:
            print(
                "Hydro mesh Brep %d exception: %s" %
                (
                    brep_index,
                    str(error)
                )
            )

        if not meshes:
            # Một patch nhỏ có thể không mesh với tolerance tinh 0.1 mm.
            # Thử lại cùng kích thước cạnh mục tiêu nhưng để Rhino chọn
            # các ràng buộc còn lại trước khi bỏ qua patch đó.
            try:
                fallback_parameters = rg.MeshingParameters()
                fallback_parameters.MaximumEdgeLength = target_edge
                meshes = rg.Mesh.CreateFromBrep(
                    brep, fallback_parameters)
                if meshes:
                    mesh_fallbacks.append(brep_index)
                    print("Hydro mesh Brep %d: fallback parameters" %
                          brep_index)
            except Exception as error:
                print("Hydro mesh Brep %d fallback exception: %s" %
                      (brep_index, str(error)))

        if not meshes:
            mesh_failures.append(brep_index)
            continue

        for mesh in meshes:
            if mesh is None:
                continue

            try:
                mesh.Faces.ConvertQuadsToTriangles()
            except Exception:
                pass

            vertices = mesh.Vertices
            faces = mesh.Faces

            for face_index in range(
                faces.Count
            ):
                face = faces[
                    face_index
                ]

                try:
                    p0 = hydro_v79_point3d(
                        vertices[face.A]
                    )
                    p1 = hydro_v79_point3d(
                        vertices[face.B]
                    )
                    p2 = hydro_v79_point3d(
                        vertices[face.C]
                    )
                except Exception:
                    continue

                # Loại tam giác suy biến.
                cross = rg.Vector3d.CrossProduct(
                    p1 - p0,
                    p2 - p0
                )

                if cross.SquareLength <= 1.0e-12:
                    continue

                triangles.append(
                    (
                        p0,
                        p1,
                        p2
                    )
                )

        if len(triangles) == triangle_count_before:
            mesh_failures.append(brep_index)

    source.mesh_failures = mesh_failures
    source.mesh_fallbacks = mesh_fallbacks
    if mesh_failures:
        Rhino.RhinoApp.WriteLine(
            "Model 112 hydro mesh warning: skipped %d/%d Breps "
            "(indices: %s); trying each draft independently" %
            (len(mesh_failures), len(source.raw_breps),
             ", ".join(str(index) for index in mesh_failures[:10]))
        )

    if not triangles:
        raise Exception(
            u"Không mesh được các mặt vỏ để tính thủy tĩnh."
        )

    source.mesh_triangles = triangles
    source.mesh_triangle_count = len(
        triangles
    )

    print(
        (
            "Hydro | mesh cache=%d triangles | "
            "target edge≈%.1f mm"
        ) % (
            len(triangles),
            model_units_to_mm(
                target_edge,
                base_params.units_per_meter
            )
        )
    )

    return triangles


def hydro_v79_snap_to_water(
    point,
    water_z,
    tolerance
):
    """Snap Z về đúng water_z nếu nằm rất gần mặt nước."""
    if abs(
        float(point.Z) -
        float(water_z)
    ) <= tolerance:
        return rg.Point3d(
            point.X,
            point.Y,
            water_z
        )

    return point


def hydro_v79_intersection_point(
    point_a,
    point_b,
    water_z
):
    """Giao điểm đoạn AB với mặt phẳng Z = water_z."""
    za = float(
        point_a.Z
    )
    zb = float(
        point_b.Z
    )

    denominator = (
        zb -
        za
    )

    if abs(denominator) <= 1.0e-12:
        return rg.Point3d(
            point_a.X,
            point_a.Y,
            water_z
        )

    fraction = (
        float(water_z) -
        za
    ) / denominator

    fraction = clamp(
        fraction,
        0.0,
        1.0
    )

    return rg.Point3d(
        lerp(
            point_a.X,
            point_b.X,
            fraction
        ),
        lerp(
            point_a.Y,
            point_b.Y,
            fraction
        ),
        water_z
    )


def hydro_v79_unique_points(
    points,
    tolerance
):
    result = []

    for point in points:
        duplicate = False

        for existing in result:
            if point.DistanceTo(
                existing
            ) <= tolerance:
                duplicate = True
                break

        if not duplicate:
            result.append(
                point
            )

    return result


def hydro_v21_triangle_water_segments(triangle, water_z, tolerance):
    """Lấy giao tuyến tam giác/mặt nước, kể cả cạnh nằm hẳn trên mặt nước.

    Một tam giác phía trên với đúng hai đỉnh tại water_z không có diện tích
    chìm, nhưng cạnh nối hai đỉnh vẫn thuộc đường nước. Nhánh clip cũ bỏ cạnh
    này vì polygon sau cắt chỉ có hai điểm.
    """
    vertices = [hydro_v79_snap_to_water(point, water_z, tolerance)
                for point in triangle]
    levels = [float(point.Z) - float(water_z) for point in vertices]
    on_plane = [index for index, level in enumerate(levels)
                if abs(level) <= tolerance]

    # Một tam giác hoàn toàn đồng phẳng không cung cấp biên ngoài duy nhất;
    # các tam giác kề hai bên mới quyết định giao tuyến thực sự.
    if len(on_plane) == 3:
        return []

    intersections = [vertices[index] for index in on_plane]
    for index in range(3):
        next_index = (index + 1) % 3
        if ((levels[index] < -tolerance and
             levels[next_index] > tolerance) or
            (levels[index] > tolerance and
             levels[next_index] < -tolerance)):
            intersections.append(hydro_v79_intersection_point(
                vertices[index], vertices[next_index], water_z))

    intersections = hydro_v79_unique_points(
        intersections, max(tolerance * 0.25, 1.0e-10))
    if len(intersections) < 2:
        return []

    if len(intersections) > 2:
        # Chỉ có thể xảy ra do dung sai ở một đỉnh. Chọn hai điểm xa nhất.
        point_a, point_b = max(
            ((a, b) for i, a in enumerate(intersections)
             for b in intersections[i + 1:]),
            key=lambda pair: hydro_v79_distance_xy(pair[0], pair[1]))
    else:
        point_a, point_b = intersections

    if hydro_v79_distance_xy(point_a, point_b) <= tolerance * 0.25:
        return []

    return [(rg.Point3d(point_a.X, point_a.Y, water_z),
             rg.Point3d(point_b.X, point_b.Y, water_z))]


def hydro_v79_clip_triangle_below_water(
    triangle,
    water_z,
    tolerance
):
    """
    Cắt một tam giác bởi nửa không gian Z <= water_z.

    Trả:
    - list tam giác phần chìm;
    - các segment nằm trên mặt đường nước do tam giác này sinh ra.
    """
    polygon = [
        hydro_v79_snap_to_water(
            triangle[0],
            water_z,
            tolerance
        ),
        hydro_v79_snap_to_water(
            triangle[1],
            water_z,
            tolerance
        ),
        hydro_v79_snap_to_water(
            triangle[2],
            water_z,
            tolerance
        )
    ]

    # Thu giao tuyến độc lập với polygon phần chìm: polygon hai đỉnh vẫn có
    # thể chứa một cạnh đường nước hợp lệ tại mép chine.
    water_segments = hydro_v21_triangle_water_segments(
        triangle, water_z, tolerance)

    output = []

    previous = polygon[-1]
    previous_inside = (
        float(previous.Z) <=
        float(water_z) + tolerance
    )

    for current in polygon:
        current_inside = (
            float(current.Z) <=
            float(water_z) + tolerance
        )

        if current_inside:
            if not previous_inside:
                output.append(
                    hydro_v79_intersection_point(
                        previous,
                        current,
                        water_z
                    )
                )

            output.append(
                current
            )
        elif previous_inside:
            output.append(
                hydro_v79_intersection_point(
                    previous,
                    current,
                    water_z
                )
            )

        previous = current
        previous_inside = current_inside

    output = hydro_v79_unique_points(
        output,
        tolerance * 0.25
    )

    if len(output) < 3:
        return [], water_segments

    # Triangulate polygon 3 hoặc 4 đỉnh theo fan.
    clipped_triangles = []

    for index in range(
        1,
        len(output) - 1
    ):
        clipped_triangles.append(
            (
                output[0],
                output[index],
                output[index + 1]
            )
        )

    return (
        clipped_triangles,
        water_segments
    )



def hydro_effective_tolerance(
    floor_mm=0.01,
    cap_mm=0.50,
    document_factor=1.0
):
    """
    Dung sai số dùng riêng cho engine thủy tĩnh.

    Lý do:
    DocumentAbsoluteTolerance phụ thuộc model units. Ví dụ document Meters
    với Absolute tolerance = 0.01 nghĩa là 10 mm, quá lớn cho việc xác định
    giao tuyến mesh-waterplane.

    Vì vậy tolerance thủy tĩnh:
    - vẫn tham khảo Document tolerance;
    - nhưng bị giới hạn trong một khoảng vật lý theo mm;
    - sau đó mới đổi về model units hiện tại.

    Mục tiêu là kết quả gần như không thay đổi khi document chuyển
    Millimeters <-> Meters.
    """
    units = float(
        GeometryUnitsPerMeter
    )

    floor_model = model_units_from_mm(
        float(floor_mm),
        units
    )

    cap_model = model_units_from_mm(
        float(cap_mm),
        units
    )

    try:
        doc_tol = (
            float(sc.doc.ModelAbsoluteTolerance) *
            float(document_factor)
        )
    except Exception:
        doc_tol = floor_model

    return max(
        floor_model,
        min(
            doc_tol,
            cap_model
        )
    )



def hydro_v79_segment_key(
    point_a,
    point_b,
    quantum
):
    """
    Key không phụ thuộc hướng segment để bỏ segment trùng.
    """
    def key_point(point):
        return (
            int(
                round(
                    float(point.X) /
                    quantum
                )
            ),
            int(
                round(
                    float(point.Y) /
                    quantum
                )
            )
        )

    key_a = key_point(
        point_a
    )
    key_b = key_point(
        point_b
    )

    if key_a <= key_b:
        return (
            key_a,
            key_b
        )

    return (
        key_b,
        key_a
    )


def hydro_v79_deduplicate_segments(
    segments,
    tolerance
):
    """
    Giữ một bản của mỗi cạnh đường nước, kể cả khi hai panel cùng trả về nó.

    Không dùng chẵn/lẻ để xóa: tại một chine trùng mớn nước, cả panel
    phía trên và phía dưới có thể cung cấp cùng một cạnh. Xóa cả hai làm
    đường bao hở dù cạnh thật vẫn tồn tại.
    """
    if not segments:
        return []

    quantum = max(
        tolerance * 0.5,
        model_units_from_mm(
            0.05,
            GeometryUnitsPerMeter
        )
    )

    unique = {}
    for point_a, point_b in segments:
        if hydro_v79_distance_xy(
            point_a,
            point_b
        ) <= tolerance * 0.1:
            continue

        key = hydro_v79_segment_key(
            point_a,
            point_b,
            quantum
        )

        if key not in unique:
            unique[key] = (
                point_a,
                point_b
            )

    return list(unique.values())


def hydro_v79_curve_to_polygon(
    curve,
    water_z
):
    """Chuyển curve gồm các line segment thành danh sách điểm polygon."""
    if curve is None:
        return []

    # Cách 1: TryGetPolyline.
    try:
        success, polyline = curve.TryGetPolyline()

        if success:
            points = [
                rg.Point3d(
                    point.X,
                    point.Y,
                    water_z
                )
                for point in polyline
            ]

            if (
                len(points) > 1 and
                points[0].DistanceTo(
                    points[-1]
                ) <= 1.0e-6
            ):
                points.pop()

            return points
    except Exception:
        pass

    # Cách 2: DuplicateSegments của PolyCurve.
    try:
        segments = curve.DuplicateSegments()

        if segments:
            points = [
                rg.Point3d(
                    segments[0].PointAtStart.X,
                    segments[0].PointAtStart.Y,
                    water_z
                )
            ]

            for segment in segments:
                end_point = segment.PointAtEnd

                points.append(
                    rg.Point3d(
                        end_point.X,
                        end_point.Y,
                        water_z
                    )
                )

            if (
                len(points) > 1 and
                points[0].DistanceTo(
                    points[-1]
                ) <= 1.0e-6
            ):
                points.pop()

            return points
    except Exception:
        pass

    return []


def hydro_v79_polygon_signed_area(
    points
):
    if points is None or len(points) < 3:
        return 0.0

    area2 = 0.0

    for index in range(
        len(points)
    ):
        point_a = points[
            index
        ]
        point_b = points[
            (index + 1) % len(points)
        ]

        area2 += (
            float(point_a.X) *
            float(point_b.Y) -
            float(point_b.X) *
            float(point_a.Y)
        )

    return 0.5 * area2



def hydro_v711_exact_waterline_curves(
    source,
    water_z
):
    """
    LẤY CONTOUR ĐƯỜNG NƯỚC TỪ BRE P NURBS.

    Ưu tiên:
        rg.Brep.CreateContourCurves(brep, plane)

    Đây là API đơn giản và thường ổn định hơn BrepPlane overload
    trong Rhino + IronPython.

    Nếu CreateContourCurves không trả curve thì mới thử BrepPlane.
    """
    if source is None or not source.raw_breps:
        return []

    plane = rg.Plane(
        rg.Point3d(
            0.0,
            0.0,
            float(water_z)
        ),
        rg.Vector3d.ZAxis
    )

    base_tol = max(
        float(sc.doc.ModelAbsoluteTolerance),
        0.01
    )

    result_curves = []

    for brep_index, brep in enumerate(
        source.raw_breps
    ):
        if brep is None:
            continue

        curves = None

        # --------------------------------------------------------------
        # ƯU TIÊN 1: CreateContourCurves.
        # --------------------------------------------------------------
        try:
            curves = rg.Brep.CreateContourCurves(
                brep,
                plane
            )
        except Exception as error:
            print(
                (
                    "Hydro CreateContourCurves | Brep %d | "
                    "exception=%s"
                ) % (
                    brep_index,
                    str(error)
                )
            )

            curves = None

        # --------------------------------------------------------------
        # ƯU TIÊN 2: BrepPlane fallback.
        # --------------------------------------------------------------
        if not curves:
            try:
                success, brep_plane_curves, points = (
                    Rhino.Geometry.Intersect.Intersection.BrepPlane(
                        brep,
                        plane,
                        max(
                            base_tol * 2.0,
                            model_units_from_mm(
                                0.02,
                                GeometryUnitsPerMeter
                            )
                        )
                    )
                )

                if success:
                    curves = brep_plane_curves
            except Exception:
                curves = None

        if not curves:
            continue

        for curve in curves:
            if curve is None:
                continue

            try:
                duplicate = curve.DuplicateCurve()
            except Exception:
                duplicate = None

            if duplicate is not None:
                result_curves.append(
                    duplicate
                )

    print(
        "Hydro | exact contour curves=%d" %
        len(result_curves)
    )

    return result_curves



def hydro_v710_sample_curve_to_polygon(
    curve,
    water_z,
    target_spacing_mm=100.0
):
    """
    Chuyển một Curve NURBS/PolyCurve kín thành polygon đủ mịn
    để tính Awp, LCF, moment quán tính và triangulate mặt nước.

    Không yêu cầu curve phải là PolylineCurve.
    """
    if curve is None:
        return []

    length = 0.0

    try:
        length = float(
            curve.GetLength()
        )
    except Exception:
        length = 0.0

    if length <= 0.0:
        return []

    spacing_model = model_units_from_mm(
        max(
            20.0,
            float(target_spacing_mm)
        ),
        GeometryUnitsPerMeter
    )

    count = int(
        max(
            32,
            min(
                2000,
                math.ceil(
                    length /
                    max(
                        spacing_model,
                        sc.doc.ModelAbsoluteTolerance
                    )
                )
            )
        )
    )

    parameters = None

    try:
        parameters = curve.DivideByCount(
            count,
            True
        )
    except Exception:
        parameters = None

    points = []

    if parameters:
        for parameter in parameters:
            try:
                point = curve.PointAt(
                    parameter
                )

                points.append(
                    rg.Point3d(
                        point.X,
                        point.Y,
                        water_z
                    )
                )
            except Exception:
                pass

    # Fallback nếu DivideByCount không hoạt động ở overload hiện tại.
    if len(points) < 3:
        domain = curve.Domain

        for index in range(
            count
        ):
            fraction = (
                float(index) /
                float(count)
            )

            parameter = (
                float(domain.T0) +
                (
                    float(domain.T1) -
                    float(domain.T0)
                ) *
                fraction
            )

            point = curve.PointAt(
                parameter
            )

            points.append(
                rg.Point3d(
                    point.X,
                    point.Y,
                    water_z
                )
            )

    # Xóa điểm lặp liên tiếp.
    clean_points = []

    point_tolerance = max(
        float(sc.doc.ModelAbsoluteTolerance),
        0.01
    )

    for point in points:
        if (
            not clean_points or
            point.DistanceTo(
                clean_points[-1]
            ) >
            point_tolerance
        ):
            clean_points.append(
                point
            )

    if (
        len(clean_points) > 2 and
        clean_points[0].DistanceTo(
            clean_points[-1]
        ) <=
        point_tolerance
    ):
        clean_points.pop()

    return clean_points


def hydro_v710_find_exact_waterplane_polygon(
    source,
    water_z
):
    """
    Ghép các curve BrepPlane thành một loop kín và lấy loop lớn nhất.

    Đây là phương pháp ưu tiên của V7.10.
    """
    exact_curves = hydro_v711_exact_waterline_curves(
        source,
        water_z
    )

    if not exact_curves:
        return None

           
    # Không để Document tolerance = 0.01 m biến thành base tolerance 10 mm.
    base_tol = hydro_effective_tolerance(
        floor_mm=0.01,
        cap_mm=0.50,
        document_factor=1.0
    )

    # Dung sai dưới đây là mm VẬT LÝ, sau đó đổi sang model units.
    tolerance_values = [
        base_tol * 2.0,
        base_tol * 5.0,
        model_units_from_mm(0.10, GeometryUnitsPerMeter),
        model_units_from_mm(0.25, GeometryUnitsPerMeter),
        model_units_from_mm(0.50, GeometryUnitsPerMeter),
        model_units_from_mm(1.00, GeometryUnitsPerMeter),
        model_units_from_mm(2.00, GeometryUnitsPerMeter),
        model_units_from_mm(3.00, GeometryUnitsPerMeter),
        model_units_from_mm(5.00, GeometryUnitsPerMeter),
        model_units_from_mm(10.00, GeometryUnitsPerMeter),
        model_units_from_mm(20.00, GeometryUnitsPerMeter)
    ]

    best_curve = None
    best_area = -1.0
    best_gap = 999999.0
    best_tolerance = None
    best_points = []

    for tolerance in tolerance_values:
        tolerance = max(
            base_tol,
            float(tolerance)
        )

        try:
            joined = rg.Curve.JoinCurves(
                exact_curves,
                tolerance
            )
        except Exception:
            joined = None

        if not joined:
            continue

        print(
            (
                "Hydro exact waterline | "
                "tol=%.3f mm | components=%d"
            ) % (
                tolerance,
                len(joined)
            )
        )

        for curve in joined:
            if curve is None:
                continue

            try:
                gap = curve.PointAtStart.DistanceTo(
                    curve.PointAtEnd
                )
            except Exception:
                gap = 999999.0

            try:
                is_closed = bool(
                    curve.IsClosed
                )
            except Exception:
                is_closed = False

            # Nếu gần kín, cho phép đóng toán học segment cuối.
            # Không cho phép vá khe quá lớn.
            max_allowed_gap = max(
                tolerance * 2.5,
                model_units_from_mm(
                    5.0,
                    GeometryUnitsPerMeter
                )
            )

            if (
                not is_closed and
                gap > max_allowed_gap
            ):
                continue

            points = hydro_v710_sample_curve_to_polygon(
                curve,
                water_z,
                75.0
            )

            if len(points) < 3:
                continue

            area = abs(
                hydro_v79_polygon_signed_area(
                    points
                )
            )

            if math.isnan(area) or math.isinf(area) or area <= 1.0e-9:
                continue

            if area > best_area:
                best_area = area
                best_curve = curve
                best_gap = gap
                best_tolerance = tolerance
                best_points = points

        # Nếu tìm được loop thật sự kín thì dừng ngay.
        if best_curve is not None:
            try:
                if best_curve.IsClosed:
                    break
            except Exception:
                pass

    if not best_points:
        print(
            (
                "Hydro | exact curves chưa tạo được loop kín "
                "từ %d curve."
            ) %
            len(exact_curves)
        )

        return None

    signed_area = hydro_v79_polygon_signed_area(
        best_points
    )

    if signed_area < 0.0:
        best_points.reverse()

    print(
        (
            "Hydro EXACT WATERLINE SUCCESS | "
            "curves=%d | polygon=%d pts | "
            "tol=%.3f mm | gap=%.3f mm | A≈%.3f m2"
        ) % (
            len(exact_curves),
            len(best_points),
            model_units_to_mm(
                float(best_tolerance or 0.0),
                GeometryUnitsPerMeter
            ),
            model_units_to_mm(
                float(best_gap),
                GeometryUnitsPerMeter
            ),
            model_area_to_m2(
                abs(signed_area),
                GeometryUnitsPerMeter
            )
        )
    )

    return (
        best_points,
        float(best_gap),
        float(best_tolerance or 0.0),
        len(exact_curves)
    )



def hydro_v79_find_waterplane_polygon(
    segments,
    water_z,
    base_params
):
    """
    Join các segment giao tuyến mesh-waterplane thành loop kín.

    Thử tolerance tăng dần. Chọn loop kín có diện tích lớn nhất.
    """
    if not segments:
        raise Exception(
            u"Không tìm được giao tuyến giữa vỏ tàu và mặt đường nước."
        )

           
    # Không để Document tolerance = 0.01 m biến thành base tolerance 10 mm.
    base_tol = hydro_effective_tolerance(
        floor_mm=0.01,
        cap_mm=0.50,
        document_factor=1.0
    )

    # Với mesh và các mặt rời, cho phép nối waterline tới 10 mm vật lý.
    tolerance_values = [
        base_tol * 2.0,
        base_tol * 5.0,
        model_units_from_mm(0.25, GeometryUnitsPerMeter),
        model_units_from_mm(0.50, GeometryUnitsPerMeter),
        model_units_from_mm(1.00, GeometryUnitsPerMeter),
        model_units_from_mm(2.00, GeometryUnitsPerMeter),
        model_units_from_mm(3.00, GeometryUnitsPerMeter),
        model_units_from_mm(5.00, GeometryUnitsPerMeter),
        model_units_from_mm(10.00, GeometryUnitsPerMeter)
    ]

    best_points = []
    best_area = 0.0
    best_tolerance = None
    best_gap = 0.0

    for tolerance in tolerance_values:
        tolerance = max(
            base_tol,
            float(tolerance)
        )

        clean_segments = hydro_v79_deduplicate_segments(
            segments,
            tolerance
        )

        line_curves = [
            rg.LineCurve(
                point_a,
                point_b
            )
            for point_a, point_b in clean_segments
        ]

        if not line_curves:
            continue

        try:
            joined_curves = rg.Curve.JoinCurves(
                line_curves,
                tolerance
            )
        except Exception:
            joined_curves = None

        if not joined_curves:
            continue

        for curve in joined_curves:
            if curve is None:
                continue

            is_closed = False
            gap = 0.0

            try:
                is_closed = bool(
                    curve.IsClosed
                )
            except Exception:
                is_closed = False

            try:
                gap = curve.PointAtStart.DistanceTo(
                    curve.PointAtEnd
                )
            except Exception:
                gap = 999999.0

            # Cho phép loop gần kín; phần polygon toán học sẽ nối endpoint cuối về đầu.
            if (
                not is_closed and
                gap > tolerance * 2.5
            ):
                continue

            points = hydro_v79_curve_to_polygon(
                curve,
                water_z
            )

            if len(points) < 3:
                continue

            # Nếu curve mở rất nhỏ thì polygon formulas vẫn tự nối last->first.
            area = abs(
                hydro_v79_polygon_signed_area(
                    points
                )
            )

            if area > best_area:
                best_area = area
                best_points = points
                best_tolerance = tolerance
                best_gap = gap

        if best_points:
            # Nếu loop đã kín ở tolerance hiện tại thì không cần tăng thêm.
            if best_gap <= tolerance:
                break

    if len(best_points) < 3:
        raise Exception(
            (
                u"Không ghép được đường bao mặt nước kín từ %d segment. "
                u"Hãy tăng mật độ mesh hoặc kiểm tra surface bị thiếu."
            ) %
            len(segments)
        )

    # Bảo đảm CCW nhìn từ +Z -> normal mặt nước hướng lên.
    signed_area = hydro_v79_polygon_signed_area(
        best_points
    )

    if signed_area < 0.0:
        best_points.reverse()

    print(
        (
            "Hydro | waterline polygon=%d pts | "
            "join tol=%.3f mm | end gap=%.3f mm | "
            "A≈%.3f m2"
        ) % (
            len(best_points),
            model_units_to_mm(
                float(best_tolerance or 0.0),
                GeometryUnitsPerMeter
            ),
            model_units_to_mm(
                float(best_gap),
                GeometryUnitsPerMeter
            ),
            model_area_to_m2(
                abs(signed_area),
                GeometryUnitsPerMeter
            )
        )
    )

    return (
        best_points,
        float(best_gap),
        float(best_tolerance or 0.0)
    )



def hydro_v711_collect_water_segment_points(
    segments,
    water_z
):
    """
    Lấy point cloud XY từ các segment giao mesh-waterplane.
    """
    points = []

    for point_a, point_b in segments or []:
        points.append(
            rg.Point3d(
                point_a.X,
                point_a.Y,
                water_z
            )
        )

        points.append(
            rg.Point3d(
                point_b.X,
                point_b.Y,
                water_z
            )
        )

    return points


def hydro_v711_waterline_envelope_polygon(
    segments,
    water_z,
    base_params
):
    """
    Dựng lại polygon đường nước từ ENVELOPE của point cloud.

    Không cần các segment phải nối topology.

    Vì Model 112:
    - đối xứng qua Y = 0;
    - tại mỗi X, biên ngoài mặt nước có một nửa rộng |Y|;
    - các seam/chine nằm bên trong có |Y| nhỏ hơn biên ngoài.

    Thuật toán:
    1. Gom endpoint của toàn bộ segment.
    2. Chia trục X thành các bin nhỏ.
    3. Tại mỗi bin lấy max(+Y) và min(-Y).
    4. Nếu một bên thiếu, mirror bên còn lại.
    5. Tạo starboard curve theo X tăng và port curve theo X giảm.
    """
    points = hydro_v711_collect_water_segment_points(
        segments,
        water_z
    )

    if len(points) < 6:
        raise Exception(
            u"Không đủ điểm giao tuyến để dựng envelope mặt nước."
        )

    length_model = float(
        base_params.length
    )

    units = float(
        base_params.units_per_meter
    )

    # Khoảng 350-500 mẫu dọc tàu; giới hạn vật lý 25-100 mm.
    bin_width = max(
        model_units_from_mm(
            25.0,
            units
        ),
        min(
            model_units_from_mm(
                100.0,
                units
            ),
            length_model / 450.0
        )
    )

    min_x = min(
        float(point.X)
        for point in points
    )

    max_x = max(
        float(point.X)
        for point in points
    )

    if max_x - min_x <= bin_width:
        raise Exception(
            u"Khoảng X của đường nước quá nhỏ."
        )

    bins = {}

    for point in points:
        x = float(
            point.X
        )

        index = int(
            round(
                (
                    x -
                    min_x
                ) /
                bin_width
            )
        )

        bins.setdefault(
            index,
            []
        ).append(
            point
        )

    starboard = []
    port = []

    # Dùng ngưỡng nhỏ để phân biệt centerline.
    center_tolerance = max(
        hydro_effective_tolerance(
            floor_mm=0.10,
            cap_mm=1.00,
            document_factor=2.0
        ),
        model_units_from_mm(
            0.50,
            base_params.units_per_meter
        )
    )

    for index in sorted(
        bins.keys()
    ):
        bin_points = bins[
            index
        ]

        if not bin_points:
            continue

        x_value = sum(
            float(point.X)
            for point in bin_points
        ) / float(
            len(bin_points)
        )

        positive_y = [
            float(point.Y)
            for point in bin_points
            if float(point.Y) >= -center_tolerance
        ]

        negative_y = [
            float(point.Y)
            for point in bin_points
            if float(point.Y) <= center_tolerance
        ]

        y_starboard = (
            max(positive_y)
            if positive_y
            else None
        )

        y_port = (
            min(negative_y)
            if negative_y
            else None
        )

        # Nếu chỉ có một bên do mesh/trim thiếu một vài đoạn,
        # dùng đối xứng hình học của Model 112.
        if y_starboard is None and y_port is not None:
            y_starboard = abs(
                y_port
            )

        if y_port is None and y_starboard is not None:
            y_port = -abs(
                y_starboard
            )

        if y_starboard is None or y_port is None:
            continue

        # Loại điểm nội bộ gần centerline nếu cùng bin có biên ngoài lớn hơn.
        half_beam = 0.5 * (
            abs(y_starboard) +
            abs(y_port)
        )

        y_starboard = half_beam
        y_port = -half_beam

        starboard.append(
            rg.Point3d(
                x_value,
                y_starboard,
                water_z
            )
        )

        port.append(
            rg.Point3d(
                x_value,
                y_port,
                water_z
            )
        )

    if len(starboard) < 5:
        raise Exception(
            u"Không đủ điểm envelope theo chiều dọc."
        )

    # Giữ bản đầy đủ trước khi lọc chuỗi để có fallback an toàn.
    full_starboard = list(
        starboard
    )

    # --------------------------------------------------------------
    # Loại các bin rỗng/gãy lớn và giữ chuỗi liên tục dài nhất.
    # --------------------------------------------------------------
    def longest_continuous_chain(points_list):
        """
        Nhận diện chuỗi đường nước theo X bằng gap thích nghi.

        dùng max_gap = 3.5 * bin_width cố định. Với mesh ở đơn vị mét,
        một vài triangle dài có thể làm endpoint cách nhau hơn ngưỡng này,
        dù đường nước thực tế vẫn liên tục.

        Ngưỡng mới lấy lớn nhất của:
        - 6 bin;
        - 1.75 lần median gap thực tế;
        - 1% chiều dài tàu.

        Đồng thời không cho vượt 8% chiều dài tàu để tránh nối nhầm hai cụm
        hoàn toàn không liên quan.
        """
        if len(points_list) < 2:
            return points_list

        x_gaps = []

        for index in range(
            1,
            len(points_list)
        ):
            gap_value = (
                float(points_list[index].X) -
                float(points_list[index - 1].X)
            )

            if gap_value > 0.0:
                x_gaps.append(
                    gap_value
                )

        if x_gaps:
            sorted_gaps = sorted(
                x_gaps
            )

            median_gap = sorted_gaps[
                len(sorted_gaps) // 2
            ]
        else:
            median_gap = bin_width

        max_gap = max(
            bin_width * 6.0,
            median_gap * 1.75,
            float(base_params.length) * 0.01
        )

        max_gap = min(
            max_gap,
            float(base_params.length) * 0.08
        )

        chains = []
        current = [
            points_list[0]
        ]

        for point in points_list[1:]:
            if (
                float(point.X) -
                float(current[-1].X)
            ) <= max_gap:
                current.append(
                    point
                )
            else:
                chains.append(
                    current
                )

                current = [
                    point
                ]

        chains.append(
            current
        )

        best_chain = max(
            chains,
            key=lambda chain: len(chain)
        )

        print(
            (
                "Hydro envelope chain | raw=%d | chains=%d | "
                "best=%d | median gap=%.1f mm | max gap=%.1f mm"
            ) % (
                len(points_list),
                len(chains),
                len(best_chain),
                model_units_to_mm(
                    median_gap,
                    base_params.units_per_meter
                ),
                model_units_to_mm(
                    max_gap,
                    base_params.units_per_meter
                )
            )
        )

        return best_chain

    starboard = longest_continuous_chain(
        starboard
    )

    # Nếu mesh rất thưa khiến thuật toán chain vẫn tách thành cụm nhỏ,
    # giữ toàn bộ envelope theo X thay vì dừng phép tính. Với Model 112
    # đường nước là đơn trị theo X nên việc nối tuyến tính qua vài khoảng
    # thiếu nhỏ là an toàn hơn việc báo lỗi.
    if len(starboard) < 5:
        print(
            (
                "Hydro envelope fallback | "
                "chuỗi tốt nhất chỉ có %d điểm -> dùng toàn bộ %d điểm envelope."
            ) % (
                len(starboard),
                len(full_starboard)
            )
        )

        starboard = full_starboard

    # Port dùng đúng X tương ứng của starboard để bảo đảm polygon đối xứng.
    port = [
        rg.Point3d(
            point.X,
            -abs(point.Y),
            water_z
        )
        for point in starboard
    ]

    # --------------------------------------------------------------
    # Bổ sung chính xác hai đầu:
    # tại bow thường half-breadth -> 0;
    # tại transom giữ half-breadth thực từ envelope.
    # --------------------------------------------------------------
    if len(starboard) < 5:
        raise Exception(
            (
                u"Không đủ dữ liệu đường nước sau khi dựng envelope "
                u"(%d điểm). Kiểm tra mesh/surface tại đúng mớn nước."
            ) %
            len(starboard)
        )

    polygon = []

    for point in starboard:
        polygon.append(
            rg.Point3d(
                point.X,
                abs(point.Y),
                water_z
            )
        )

    for point in reversed(
        port
    ):
        polygon.append(
            rg.Point3d(
                point.X,
                -abs(point.Y),
                water_z
            )
        )

    # Xóa các điểm liên tiếp gần nhau.
    clean_polygon = []

    point_tol = max(
        hydro_effective_tolerance(
            floor_mm=0.10,
            cap_mm=1.00,
            document_factor=2.0
        ),
        model_units_from_mm(
            0.50,
            base_params.units_per_meter
        )
    )

    for point in polygon:
        if (
            not clean_polygon or
            point.DistanceTo(
                clean_polygon[-1]
            ) > point_tol
        ):
            clean_polygon.append(
                point
            )

    if len(clean_polygon) < 6:
        raise Exception(
            u"Polygon envelope mặt nước không đủ điểm."
        )

    signed_area = hydro_v79_polygon_signed_area(
        clean_polygon
    )

    if signed_area < 0.0:
        clean_polygon.reverse()
        signed_area = -signed_area

    # Đánh giá độ khép kín hình học:
    end_gap = clean_polygon[0].DistanceTo(
        clean_polygon[-1]
    )

    print(
        (
            "Hydro WATERLINE ENVELOPE SUCCESS | "
            "raw points=%d | bins=%d | polygon=%d pts | "
            "dx=%.1f mm | A≈%.3f m2"
        ) % (
            len(points),
            len(bins),
            len(clean_polygon),
            model_units_to_mm(
                bin_width,
                base_params.units_per_meter
            ),
            model_area_to_m2(
                signed_area,
                base_params.units_per_meter
            )
        )
    )

    return (
        clean_polygon,
        end_gap,
        bin_width
    )



def hydro_v21_exact_curve_segments(source, water_z):
    """Lấy mẫu từng curve Brep khi các curve rời không Join thành loop."""
    segments = []
    for curve in hydro_v711_exact_waterline_curves(source, water_z):
        points = hydro_v710_sample_curve_to_polygon(
            curve, water_z, target_spacing_mm=75.0)
        for index in range(1, len(points)):
            if hydro_v79_distance_xy(points[index - 1], points[index]) > 1.0e-10:
                segments.append((points[index - 1], points[index]))
        try:
            closed = bool(curve.IsClosed)
        except Exception:
            closed = False
        if closed and len(points) > 2:
            if hydro_v79_distance_xy(points[-1], points[0]) > 1.0e-10:
                segments.append((points[-1], points[0]))
    return segments


def hydro_v21_recover_mesh_waterplane(segments, water_z, base_params,
                                     source=None):
    """Thử curve Brep rời rồi mesh; chỉ nhận polygon có diện tích thật."""
    failures = []
    candidates = []
    if source is not None:
        try:
            exact_segments = hydro_v21_exact_curve_segments(source, water_z)
            if exact_segments:
                candidates.append(("exact_curve_envelope", exact_segments,
                                   hydro_v711_waterline_envelope_polygon))
        except Exception as error:
            failures.append("exact_curve_sampling: %s" % str(error))
    candidates.extend((
        ("mesh_outer_envelope", segments,
         hydro_v711_waterline_envelope_polygon),
        ("mesh_joined_loop", segments, hydro_v79_find_waterplane_polygon)
    ))
    for method, candidate_segments, builder in candidates:
        try:
            polygon, gap, join_tolerance = builder(
                candidate_segments, water_z, base_params)
            _, properties = hydro_v79_waterplane_triangles(polygon, water_z)
            if (not is_finite_number(properties["area_mm2"]) or
                    properties["bwl_mm"] <= 0.0 or
                    properties["lwl_mm"] <= 0.0):
                raise Exception(u"Đường bao mặt nước có kích thước suy biến.")
            print("Hydro waterplane recovery | %s | A=%.3f m2 | "
                  "BWL=%.3f m" %
                  (method, model_area_to_m2(properties["area_mm2"],
                                            base_params.units_per_meter),
                   model_units_to_meters(properties["bwl_mm"],
                                         base_params.units_per_meter)))
            return polygon, gap, join_tolerance, method
        except Exception as error:
            failures.append("%s: %s" % (method, str(error)))
            Rhino.RhinoApp.WriteLine(
                "Model 112 hydro waterplane %s failed: %s" %
                (method, str(error)))
    raise Exception(u"Không dựng được mặt nước hợp lệ từ Brep/mesh: %s" %
                    u"; ".join(failures))


def hydro_v79_polygon_properties(
    points
):
    """
    Tính Awp, centroid, Ix/Iy quanh centroid từ polygon XY.
    Đơn vị đầu vào: mm -> area mm2, inertia mm4.
    """
    if points is None or len(points) < 3:
        raise Exception(
            u"Đường bao mặt nước không đủ điểm."
        )

    area2 = 0.0
    cx_numerator = 0.0
    cy_numerator = 0.0
    ix_origin = 0.0
    iy_origin = 0.0

    min_x = None
    max_x = None
    min_y = None
    max_y = None

    for index in range(
        len(points)
    ):
        point_a = points[
            index
        ]
        point_b = points[
            (index + 1) % len(points)
        ]

        x0 = float(
            point_a.X
        )
        y0 = float(
            point_a.Y
        )
        x1 = float(
            point_b.X
        )
        y1 = float(
            point_b.Y
        )

        cross = (
            x0 * y1 -
            x1 * y0
        )

        area2 += cross

        cx_numerator += (
            x0 +
            x1
        ) * cross

        cy_numerator += (
            y0 +
            y1
        ) * cross

        ix_origin += (
            y0 * y0 +
            y0 * y1 +
            y1 * y1
        ) * cross

        iy_origin += (
            x0 * x0 +
            x0 * x1 +
            x1 * x1
        ) * cross

        min_x = (
            x0
            if min_x is None
            else min(
                min_x,
                x0
            )
        )
        max_x = (
            x0
            if max_x is None
            else max(
                max_x,
                x0
            )
        )
        min_y = (
            y0
            if min_y is None
            else min(
                min_y,
                y0
            )
        )
        max_y = (
            y0
            if max_y is None
            else max(
                max_y,
                y0
            )
        )

    area = (
        area2 *
        0.5
    )

    if abs(area) <= 1.0e-9:
        raise Exception(
            u"Diện tích polygon mặt nước bằng 0."
        )

    # Nếu polygon CW thì đổi dấu toàn bộ các tích phân.
    sign = (
        1.0
        if area > 0.0
        else -1.0
    )

    area = abs(
        area
    )

    cx = (
        cx_numerator /
        (3.0 * area2)
    )

    cy = (
        cy_numerator /
        (3.0 * area2)
    )

    ix_origin = (
        sign *
        ix_origin /
        12.0
    )

    iy_origin = (
        sign *
        iy_origin /
        12.0
    )

    ix_centroid = max(
        0.0,
        ix_origin -
        area * cy * cy
    )

    iy_centroid = max(
        0.0,
        iy_origin -
        area * cx * cx
    )

    return {
        "area_mm2": area,
        "centroid_x_mm": cx,
        "centroid_y_mm": cy,
        "ix_mm4": ix_centroid,
        "iy_mm4": iy_centroid,
        "lwl_mm": max(
            0.0,
            max_x - min_x
        ),
        "bwl_mm": max(
            0.0,
            max_y - min_y
        ),
        "min_x_mm": min_x,
        "max_x_mm": max_x
    }


def hydro_v79_triangle_area_vector(
    point_0,
    point_1,
    point_2
):
    return (
        rg.Vector3d.CrossProduct(
            point_1 - point_0,
            point_2 - point_0
        ) *
        0.5
    )


def hydro_v79_orient_hull_triangle_outward(
    triangle,
    interior_reference
):
    """
    Định hướng triangle ra ngoài bằng một điểm tham chiếu nằm trong phần chìm.
    """
    point_0 = triangle[0]
    point_1 = triangle[1]
    point_2 = triangle[2]

    normal = rg.Vector3d.CrossProduct(
        point_1 - point_0,
        point_2 - point_0
    )

    center = rg.Point3d(
        (
            point_0.X +
            point_1.X +
            point_2.X
        ) / 3.0,
        (
            point_0.Y +
            point_1.Y +
            point_2.Y
        ) / 3.0,
        (
            point_0.Z +
            point_1.Z +
            point_2.Z
        ) / 3.0
    )

    outward_guess = (
        center -
        interior_reference
    )

    if (
        normal *
        outward_guess
    ) < 0.0:
        return (
            point_0,
            point_2,
            point_1
        )

    return (
        point_0,
        point_1,
        point_2
    )


def hydro_v79_waterplane_triangles(
    polygon_points,
    water_z
):
    """
    Triangulate mặt đường nước bằng fan quanh centroid polygon.

    Với waterplane của Model 112 dạng đơn giản/convex, fan triangulation ổn định.
    Normal được định hướng +Z.
    """
    properties = hydro_v79_polygon_properties(
        polygon_points
    )

    center = rg.Point3d(
        properties[
            "centroid_x_mm"
        ],
        properties[
            "centroid_y_mm"
        ],
        water_z
    )

    triangles = []

    for index in range(
        len(polygon_points)
    ):
        point_a = polygon_points[
            index
        ]
        point_b = polygon_points[
            (index + 1) % len(polygon_points)
        ]

        triangle = (
            center,
            point_a,
            point_b
        )

        normal = rg.Vector3d.CrossProduct(
            point_a - center,
            point_b - center
        )

        # Outward của phần chìm tại mặt nước là +Z.
        if normal.Z < 0.0:
            triangle = (
                center,
                point_b,
                point_a
            )

        triangles.append(
            triangle
        )

    return (
        triangles,
        properties
    )


def hydro_v79_integrate_closed_triangle_surface(
    hull_triangles,
    cap_triangles,
    base_params,
    draft_mm
):
    """
    Tích phân thể tích và centroid bằng tetrahedron có đỉnh gốc reference_origin.

    Công thức cho mỗi triangle:
        dV = dot(a, cross(b,c)) / 6

    với a,b,c là vector từ reference_origin tới 3 đỉnh triangle.
    """
    reference_origin = rg.Point3d(
        float(base_params.length) * 0.5,
        0.0,
        float(base_params.baseline_z)
    )

    interior_reference = rg.Point3d(
        float(base_params.length) * 0.5,
        0.0,
        (
            float(base_params.baseline_z) +
            float(draft_mm) * 0.5
        )
    )

    signed_volume = 0.0
    first_moment_x = 0.0
    first_moment_y = 0.0
    first_moment_z = 0.0

    area_vector_sum = rg.Vector3d(
        0.0,
        0.0,
        0.0
    )

    total_closed_area = 0.0
    wetted_area = 0.0

    oriented_hull_triangles = []

    for triangle in hull_triangles:
        oriented = hydro_v79_orient_hull_triangle_outward(
            triangle,
            interior_reference
        )

        oriented_hull_triangles.append(
            oriented
        )

    all_triangles = []

    for triangle in oriented_hull_triangles:
        all_triangles.append(
            (
                triangle,
                True
            )
        )

    for triangle in cap_triangles:
        all_triangles.append(
            (
                triangle,
                False
            )
        )

    for triangle, is_hull in all_triangles:
        point_0 = triangle[0]
        point_1 = triangle[1]
        point_2 = triangle[2]

        vector_a = (
            point_0 -
            reference_origin
        )
        vector_b = (
            point_1 -
            reference_origin
        )
        vector_c = (
            point_2 -
            reference_origin
        )

        cross_bc = rg.Vector3d.CrossProduct(
            vector_b,
            vector_c
        )

        tetra_volume = (
            vector_a *
            cross_bc
        ) / 6.0

        tetra_centroid = rg.Point3d(
            (
                reference_origin.X +
                point_0.X +
                point_1.X +
                point_2.X
            ) / 4.0,
            (
                reference_origin.Y +
                point_0.Y +
                point_1.Y +
                point_2.Y
            ) / 4.0,
            (
                reference_origin.Z +
                point_0.Z +
                point_1.Z +
                point_2.Z
            ) / 4.0
        )

        signed_volume += tetra_volume

        first_moment_x += (
            tetra_volume *
            tetra_centroid.X
        )
        first_moment_y += (
            tetra_volume *
            tetra_centroid.Y
        )
        first_moment_z += (
            tetra_volume *
            tetra_centroid.Z
        )

        area_vector = hydro_v79_triangle_area_vector(
            point_0,
            point_1,
            point_2
        )

        area_vector_sum += area_vector

        triangle_area = (
            area_vector.Length
        )

        total_closed_area += triangle_area

        if is_hull:
            wetted_area += triangle_area

    if abs(signed_volume) <= 1.0e-6:
        raise Exception(
            u"Tích phân mặt cho thể tích bằng 0."
        )

    # Nếu orientation tổng thể cho volume âm, đổi dấu tích phân.
    if signed_volume < 0.0:
        signed_volume = -signed_volume
        first_moment_x = -first_moment_x
        first_moment_y = -first_moment_y
        first_moment_z = -first_moment_z

    centroid = rg.Point3d(
        first_moment_x /
        signed_volume,
        first_moment_y /
        signed_volume,
        first_moment_z /
        signed_volume
    )

    closure_ratio = (
        area_vector_sum.Length /
        total_closed_area
        if total_closed_area > 0.0
        else 1.0
    )

    return {
        "volume_mm3": signed_volume,
        "centroid": centroid,
        "wetted_mm2": wetted_area,
        "closure_ratio": closure_ratio,
        "hull_triangle_count": len(
            oriented_hull_triangles
        ),
        "cap_triangle_count": len(
            cap_triangles
        )
    }



def hydro_exact_wetted_area_from_surfaces(
    source,
    base_params,
    draft_mm
):
    """
    Tính diện tích mặt ướt trực tiếp trên các Brep/NURBS nguồn.

    Không cộng mặt waterplane cap.
    Không lấy diện tích tam giác mesh nếu phép Split Brep thành công.

    Trả:
        (area_mm2, patch_count, method)
    hoặc None nếu có mặt cắt thất bại -> caller dùng mesh fallback.
    """
    if source is None or not source.raw_breps:
        return None

    water_z = (
        float(base_params.baseline_z) +
        float(draft_mm)
    )

    split_tolerance = hydro_effective_tolerance(
        floor_mm=0.02,
        cap_mm=0.25,
        document_factor=0.5
    )

    plane, cutter_brep = create_hydro_waterplane_cutter(
        base_params,
        draft_mm
    )

    total_area = 0.0
    patch_count = 0
    split_failure_count = 0

    for brep in source.raw_breps:
        if brep is None:
            continue

        bbox = hydro_piece_bbox(
            brep
        )

        if bbox is None:
            continue

        # Hoàn toàn trên mặt nước.
        if float(
            bbox.Min.Z
        ) >= water_z - split_tolerance:
            continue

        pieces = hydro_split_one_surface_below_water(
            brep,
            cutter_brep,
            water_z,
            split_tolerance
        )

        # Nếu mặt thực sự cắt qua waterplane mà Split không cho phần dưới,
        # không dùng tổng area thiếu; quay về mesh fallback.
        crosses_water = (
            float(bbox.Min.Z) <
            water_z -
            split_tolerance and
            float(bbox.Max.Z) >
            water_z +
            split_tolerance
        )

        if crosses_water and not pieces:
            split_failure_count += 1
            continue

        for piece in pieces or []:
            props = None

            try:
                props = rg.AreaMassProperties.Compute(
                    piece
                )
            except Exception:
                props = None

            if props is None:
                if crosses_water:
                    split_failure_count += 1
                continue

            area = abs(
                float(
                    props.Area
                )
            )

            if area > 0.0:
                total_area += area
                patch_count += 1

    if (
        split_failure_count > 0 or
        total_area <= 0.0
    ):
        print(
            (
                "Hydro exact wetted fallback | "
                "split failures=%d | area=%.6g"
            ) % (
                split_failure_count,
                total_area
            )
        )
        return None

    return (
        total_area,
        patch_count,
        "exact_brep_underwater_area"
    )


def hydro_v79_surface_integration_at_draft(
    source,
    base_params,
    draft_m,
    density_t_per_m3
):
    """
    Hàm chính của module thủy tĩnh.
    """
    units = float(
        base_params.units_per_meter
    )

    draft_mm = (
        float(draft_m) *
        units
    )

    water_z = (
        float(base_params.baseline_z) +
        draft_mm
    )

    full_triangles = hydro_v79_mesh_source_triangles(
        source,
        base_params
    )

           
    # Tolerance cắt tam giác-waterplane giữ ở thang vật lý nhỏ.
    # Với document Meters, AbsoluteTolerance=0.01 m không được phép
    # biến clip tolerance thành 20 mm.
    clip_tolerance = hydro_effective_tolerance(
        floor_mm=0.05,
        cap_mm=0.50,
        document_factor=2.0
    )

    print(
        (
            "Hydro numeric tolerance | Document=%s | "
            "DocAbsTol=%.3f mm | clipTol=%.3f mm"
        ) % (
            document_unit_name(),
            model_units_to_mm(
                float(sc.doc.ModelAbsoluteTolerance),
                base_params.units_per_meter
            ),
            model_units_to_mm(
                clip_tolerance,
                base_params.units_per_meter
            )
        )
    )

    underwater_triangles = []
    water_segments = []

    for triangle in full_triangles:
        (
            clipped_triangles,
            triangle_water_segments
        ) = hydro_v79_clip_triangle_below_water(
            triangle,
            water_z,
            clip_tolerance
        )

        underwater_triangles.extend(
            clipped_triangles
        )

        water_segments.extend(
            triangle_water_segments
        )

    if not underwater_triangles:
        raise Exception(
            u"Không có tam giác vỏ nào nằm dưới mớn nước."
        )

    if not water_segments:
        raise Exception(
            u"Không tạo được giao tuyến mặt nước từ mesh vỏ."
        )

    # --------------------------------------------------------------
            
    # ƯU TIÊN đường nước chính xác từ giao Brep NURBS - Plane.
    # Mesh segments chỉ dùng làm fallback.
    # --------------------------------------------------------------
    exact_waterline = hydro_v710_find_exact_waterplane_polygon(
        source,
        water_z
    )

    if exact_waterline is not None:
        (
            water_polygon,
            waterline_gap_mm,
            waterline_join_tolerance_mm,
            exact_waterline_curve_count
        ) = exact_waterline

        waterline_method = (
            "exact_brep_plane"
        )
    else:
        print(
            (
                "Hydro | exact contour chưa kín; "
                "dựng WATERLINE ENVELOPE từ %d mesh segments."
            ) %
            len(water_segments)
        )

        (
            water_polygon,
            waterline_gap_mm,
            waterline_join_tolerance_mm,
            waterline_method
        ) = hydro_v21_recover_mesh_waterplane(
            water_segments, water_z, base_params, source
        )
        exact_waterline_curve_count = 0

    # A closed Brep intersection can still have a degenerate sampled XY
    # contour (notably around a centreline keel with Bk=0). Retry once
    # with the independently assembled mesh outer envelope in that case.
    try:
        (
            cap_triangles,
            waterplane_properties
        ) = hydro_v79_waterplane_triangles(water_polygon, water_z)
    except Exception as exact_error:
        if waterline_method != "exact_brep_plane":
            raise
        Rhino.RhinoApp.WriteLine(
            "Model 112 hydro exact waterline rejected at T=%.3f m: %s" %
            (float(draft_m), str(exact_error))
        )
        (
            water_polygon,
            waterline_gap_mm,
            waterline_join_tolerance_mm,
            waterline_method
        ) = hydro_v21_recover_mesh_waterplane(
            water_segments, water_z, base_params, source
        )
        exact_waterline_curve_count = 0
        (
            cap_triangles,
            waterplane_properties
        ) = hydro_v79_waterplane_triangles(water_polygon, water_z)

    integration = hydro_v79_integrate_closed_triangle_surface(
        underwater_triangles,
        cap_triangles,
        base_params,
        draft_mm
    )

    volume_mm3 = float(
        integration[
            "volume_mm3"
        ]
    )

    centroid = integration[
        "centroid"
    ]

    mm3_per_m3 = (
        units *
        units *
        units
    )

    mm2_per_m2 = (
        units *
        units
    )

    volume_m3 = (
        volume_mm3 /
        mm3_per_m3
    )

    displacement_t = (
        volume_m3 *
        float(
            density_t_per_m3
        )
    )

    lcb_m = (
        float(centroid.X) /
        units
    )

    tcb_m = (
        float(centroid.Y) /
        units
    )

    kb_m = (
        (
            float(centroid.Z) -
            float(base_params.baseline_z)
        ) /
        units
    )

    awp_m2 = (
        waterplane_properties[
            "area_mm2"
        ] /
        mm2_per_m2
    )

    lcf_m = (
        waterplane_properties[
            "centroid_x_mm"
        ] /
        units
    )

    tcf_m = (
        waterplane_properties[
            "centroid_y_mm"
        ] /
        units
    )

    lwl_m = (
        waterplane_properties[
            "lwl_mm"
        ] /
        units
    )

    bwl_m = (
        waterplane_properties[
            "bwl_mm"
        ] /
        units
    )

    # --------------------------------------------------------------
    # WETTED AREA:
    # ưu tiên diện tích Brep/NURBS đã Split theo waterplane.
    # Mesh chỉ là fallback nếu một surface không Split được.
    # --------------------------------------------------------------
    wetted_exact = hydro_exact_wetted_area_from_surfaces(
        source,
        base_params,
        draft_mm
    )

    if wetted_exact is not None:
        (
            wetted_mm2,
            wetted_patch_count,
            wetted_method
        ) = wetted_exact
    else:
        wetted_mm2 = float(
            integration[
                "wetted_mm2"
            ]
        )
        wetted_patch_count = int(
            integration[
                "hull_triangle_count"
            ]
        )
        wetted_method = (
            "mesh_triangle_fallback"
        )

    wetted_m2 = (
        wetted_mm2 /
        mm2_per_m2
    )

    length_m = (
        float(base_params.length) /
        units
    )

    beam_m = (
        float(base_params.beam) /
        units
    )

    # --------------------------------------------------------------
    # BLOCK COEFFICIENT
    #
    # Để đối chiếu trực tiếp với bảng Hydrostatics của Maxsurf đang dùng
    # trong đề tài, Cb chính được tính theo hộp bao phần chìm tại waterline:
    #
    #       Cb = V / (LWL * BWL * T)
    #
    # Đồng thời vẫn giữ Cb_Lmax theo Lmax*Bmax*T để không mất quy ước cũ.
    # --------------------------------------------------------------
    cb_lmax = 0.0

    block_denominator_lmax = (
        length_m *
        beam_m *
        float(draft_m)
    )

    if block_denominator_lmax > 0.0:
        cb_lmax = (
            volume_m3 /
            block_denominator_lmax
        )

    cb = 0.0

    block_denominator_waterline = (
        lwl_m *
        bwl_m *
        float(draft_m)
    )

    if block_denominator_waterline > 0.0:
        cb = (
            volume_m3 /
            block_denominator_waterline
        )

    cwp = 0.0

    waterplane_denominator = (
        lwl_m *
        bwl_m
    )

    if waterplane_denominator > 0.0:
        cwp = (
            awp_m2 /
            waterplane_denominator
        )

    bmt_mm = 0.0
    bml_mm = 0.0

    if volume_mm3 > 0.0:
        bmt_mm = (
            waterplane_properties[
                "ix_mm4"
            ] /
            volume_mm3
        )

        bml_mm = (
            waterplane_properties[
                "iy_mm4"
            ] /
            volume_mm3
        )

    bmt_m = (
        bmt_mm /
        units
    )

    bml_m = (
        bml_mm /
        units
    )

    kmt_m = (
        kb_m +
        bmt_m
    )

    kml_m = (
        kb_m +
        bml_m
    )

    closure_ratio = float(
        integration[
            "closure_ratio"
        ]
    )

    print(
        (
            "Hydro RESULT | T=%.3f m | V=%.3f m3 | "
            "LCB=%.3f m | KB=%.3f m | "
            "TCB=%.4f m | closure=%.5f%%"
        ) % (
            float(draft_m),
            volume_m3,
            lcb_m,
            kb_m,
            tcb_m,
            closure_ratio * 100.0
        )
    )

    if closure_ratio > 0.01:
        print(
            (
                "CANH BAO Hydro: closure vector ratio %.3f%% "
                "khá lớn; nên đối chiếu V/LCB/KB với Orca3D."
            ) %
            (
                closure_ratio *
                100.0
            )
        )

    return {
        "draft_m": float(
            draft_m
        ),
        "density_t_m3": float(
            density_t_per_m3
        ),
        "volume_m3": volume_m3,
        "displacement_t": displacement_t,
        "lcb_m": lcb_m,
        "tcb_m": tcb_m,
        "kb_m": kb_m,
        "awp_m2": awp_m2,
        "lcf_m": lcf_m,
        "tcf_m": tcf_m,
        "lwl_m": lwl_m,
        "bwl_m": bwl_m,
        "cb": cb,
        "cb_lmax": cb_lmax,
        "cwp": cwp,
        "bmt_m": bmt_m,
        "kmt_m": kmt_m,
        "bml_m": bml_m,
        "kml_m": kml_m,
        "wetted_m2": wetted_m2,
        "wetted_method": wetted_method,
        "wetted_patch_count": int(
            wetted_patch_count
        ),
        "lcb_percent_L": (
            100.0 *
            lcb_m /
            length_m
            if length_m > 0.0
            else 0.0
        ),
        "lcf_percent_L": (
            100.0 *
            lcf_m /
            length_m
            if length_m > 0.0
            else 0.0
        ),

                                
        "hydro_method": (
            "surface_triangle_integration"
        ),
        "closure_ratio": closure_ratio,
        "mesh_triangle_count": int(
            source.mesh_triangle_count
        ),
        "mesh_skipped_breps": list(source.mesh_failures),
        "mesh_fallback_breps": list(source.mesh_fallbacks),
        "construction_warnings": list(source.construction_warnings),
        "underwater_triangle_count": int(
            integration[
                "hull_triangle_count"
            ]
        ),
        "waterplane_point_count": len(
            water_polygon
        ),
        "waterline_gap_mm": model_units_to_mm(
            float(waterline_gap_mm),
            base_params.units_per_meter
        ),
        "waterline_join_tolerance_mm": model_units_to_mm(
            float(waterline_join_tolerance_mm),
            base_params.units_per_meter
        ),
        "waterline_method": waterline_method,
        "exact_waterline_curve_count": int(
            exact_waterline_curve_count
        )
    }




def hydro_result_quality(result):
    """Cảnh báo rõ khi nước từ mesh có thể che khe hở đường nước NURBS."""
    if result.get("status") == "INVALID":
        return ("INVALID", TEXT_TYPE(result.get("error_message", "")))
    if result.get("hydro_method") == "zero_draft":
        return ("VALID", u"T = 0: không có phần chìm sau khi cắt hình học tại Baseline.")
    notes = []
    if result.get("mesh_skipped_breps"):
        notes.append(u"%d mặt Brep không mesh được (chỉ số %s); "
                     u"V/LCB/KB có thể thiếu phần vỏ" %
                     (len(result["mesh_skipped_breps"]),
                      ", ".join(str(index) for index in
                                result["mesh_skipped_breps"][:10])))
    if result.get("mesh_fallback_breps"):
        notes.append(u"%d mặt mesh bằng tham số dự phòng" %
                     len(result["mesh_fallback_breps"]))
    notes.extend(result.get("construction_warnings", []))
    closure = float(result.get("closure_ratio", 0.0))
    if closure > 0.01:
        notes.append(u"mặt tích phân chưa khép (closure %.2f%%)" % (100.0 * closure))
    if result.get("waterline_method") != "exact_brep_plane":
        notes.append(u"đường nước Brep–Plane chưa kín; dùng bao đường nước từ mesh")
    gap = float(result.get("waterline_gap_mm", 0.0))
    join_tol = float(result.get("waterline_join_tolerance_mm", 0.0))
    if gap > max(join_tol, 0.01):
        notes.append(u"khe đường nước %.3f mm > ngưỡng ghép %.3f mm" % (gap, join_tol))
    if result.get("wetted_method") == "mesh_triangle_fallback":
        notes.append(u"diện tích ướt tính từ mesh")
    if not notes:
        return ("VALID", u"Đường nước Brep–Plane; closure đạt ngưỡng 1%.")
    return ("WARNING", u"; ".join(notes) + u". Kiểm tra ShowEdges và đối chiếu trước khi dùng.")



def zero_hydrostatic_result(
    base_params,
    density_t_per_m3
):
    """Hàng T=0.000: xuất 0 thay vì báo lỗi để làm mốc đầu bảng."""
    return {
        "draft_m": 0.0,
        "density_t_m3": float(density_t_per_m3),
        "volume_m3": 0.0,
        "displacement_t": 0.0,
        "lcb_m": 0.0,
        "tcb_m": 0.0,
        "kb_m": 0.0,
        "awp_m2": 0.0,
        "lcf_m": 0.0,
        "tcf_m": 0.0,
        "lwl_m": 0.0,
        "bwl_m": 0.0,
        "cb": 0.0,
        "cb_lmax": 0.0,
        "cwp": 0.0,
        "bmt_m": 0.0,
        "kmt_m": 0.0,
        "bml_m": 0.0,
        "kml_m": 0.0,
        "wetted_m2": 0.0,
        "wetted_method": "zero_draft",
        "wetted_patch_count": 0,
        "lcb_percent_L": 0.0,
        "lcf_percent_L": 0.0,
        "hydro_method": "zero_draft",
        "closure_ratio": 0.0,
        "mesh_triangle_count": 0,
        "underwater_triangle_count": 0,
        "waterplane_point_count": 0,
        "waterline_gap_mm": 0.0,
        "waterline_join_tolerance_mm": 0.0,
        "waterline_method": "zero_draft",
        "exact_waterline_curve_count": 0
    }

def calculate_hydrostatic_at_draft(
    closed_hull,
    base_params,
    draft_m,
    density_t_per_m3
):
    """
    Ưu tiên engine tích phân mặt, không cần IsSolid.

    Tên tham số closed_hull được giữ để không phải sửa toàn bộ UI cũ.
    Đối tượng này là HydroSurfaceSource.
    """
    units = float(
        base_params.units_per_meter
    )

    draft_mm = (
        float(draft_m) *
        units
    )

    if draft_mm < 0.0:
        raise Exception(
            u"Mớn nước không được âm."
        )

    # V20: T=0 không còn bị cưỡng bức toàn bộ kết quả về 0.
    # Engine vẫn cắt hình học thật tại Baseline; chỉ trả zero nếu thực sự
    # không có phần chìm/giao tuyến hợp lệ tại mức này.

    if draft_mm >= float(
        base_params.depth
    ):
        raise Exception(
            u"Mớn nước tính toán phải nhỏ hơn chiều cao mạn H."
        )

    if isinstance(
        closed_hull,
        HydroSurfaceSource
    ):
        try:
            return hydro_v79_surface_integration_at_draft(
                closed_hull,
                base_params,
                draft_m,
                density_t_per_m3
            )
        except Exception as hydro_error:
            if abs(draft_mm) <= 1.0e-12:
                message = TEXT_TYPE(hydro_error)
                if (
                    u"Không có tam giác vỏ nào nằm dưới mớn nước" in message or
                    u"Không tạo được giao tuyến mặt nước" in message
                ):
                    return zero_hydrostatic_result(
                        base_params,
                        density_t_per_m3
                    )
            raise

    # Fallback chỉ để tương thích nếu một đoạn code cũ truyền Brep solid.
    underwater = create_underwater_solid(
        closed_hull,
        base_params,
        draft_mm
    )

    volume_props = rg.VolumeMassProperties.Compute(
        underwater
    )

    if volume_props is None:
        raise Exception(
            u"Rhino không tính được VolumeMassProperties của phần chìm."
        )

    volume_mm3 = abs(
        float(
            volume_props.Volume
        )
    )

    if volume_mm3 <= 0.0:
        raise Exception(
            u"Thể tích phần chìm bằng 0."
        )

    centroid = volume_props.Centroid
    water_z = (
        float(base_params.baseline_z) +
        draft_mm
    )

    wp = get_waterplane_face_data(
        underwater,
        water_z
    )

    total_surface_mm2 = 0.0

    try:
        total_area_props = rg.AreaMassProperties.Compute(
            underwater
        )

        if total_area_props is not None:
            total_surface_mm2 = float(
                total_area_props.Area
            )
    except Exception:
        total_surface_mm2 = 0.0

    wetted_mm2 = max(
        0.0,
        total_surface_mm2 -
        wp["area_mm2"]
    )

    mm3_per_m3 = (
        units *
        units *
        units
    )

    mm2_per_m2 = (
        units *
        units
    )

    volume_m3 = (
        volume_mm3 /
        mm3_per_m3
    )

    displacement_t = (
        volume_m3 *
        float(
            density_t_per_m3
        )
    )

    lcb_m = (
        float(
            centroid.X
        ) /
        units
    )

    tcb_m = (
        float(
            centroid.Y
        ) /
        units
    )

    kb_m = (
        (
            float(centroid.Z) -
            float(base_params.baseline_z)
        ) /
        units
    )

    awp_m2 = (
        wp["area_mm2"] /
        mm2_per_m2
    )

    lcf_m = (
        wp["centroid_x_mm"] /
        units
    )

    tcf_m = (
        wp["centroid_y_mm"] /
        units
    )

    lwl_m = (
        wp["lwl_mm"] /
        units
    )

    bwl_m = (
        wp["bwl_mm"] /
        units
    )

    wetted_m2 = (
        wetted_mm2 /
        mm2_per_m2
    )

    length_m = (
        float(base_params.length) /
        units
    )

    beam_m = (
        float(base_params.beam) /
        units
    )

    # --------------------------------------------------------------
    # BLOCK COEFFICIENT
    #
    # Để đối chiếu trực tiếp với bảng Hydrostatics của Maxsurf đang dùng
    # trong đề tài, Cb chính được tính theo hộp bao phần chìm tại waterline:
    #
    #       Cb = V / (LWL * BWL * T)
    #
    # Đồng thời vẫn giữ Cb_Lmax theo Lmax*Bmax*T để không mất quy ước cũ.
    # --------------------------------------------------------------
    cb_lmax = 0.0

    block_denominator_lmax = (
        length_m *
        beam_m *
        float(draft_m)
    )

    if block_denominator_lmax > 0.0:
        cb_lmax = (
            volume_m3 /
            block_denominator_lmax
        )

    cb = 0.0

    block_denominator_waterline = (
        lwl_m *
        bwl_m *
        float(draft_m)
    )

    if block_denominator_waterline > 0.0:
        cb = (
            volume_m3 /
            block_denominator_waterline
        )

    cwp = 0.0

    waterplane_denominator = (
        lwl_m *
        bwl_m
    )

    if waterplane_denominator > 0.0:
        cwp = (
            awp_m2 /
            waterplane_denominator
        )

    bmt_mm = (
        wp["ix_mm4"] /
        volume_mm3
        if volume_mm3 > 0.0
        else 0.0
    )

    bml_mm = (
        wp["iy_mm4"] /
        volume_mm3
        if volume_mm3 > 0.0
        else 0.0
    )

    bmt_m = (
        bmt_mm /
        units
    )

    bml_m = (
        bml_mm /
        units
    )

    return {
        "draft_m": float(draft_m),
        "density_t_m3": float(density_t_per_m3),
        "volume_m3": volume_m3,
        "displacement_t": displacement_t,
        "lcb_m": lcb_m,
        "tcb_m": tcb_m,
        "kb_m": kb_m,
        "awp_m2": awp_m2,
        "lcf_m": lcf_m,
        "tcf_m": tcf_m,
        "lwl_m": lwl_m,
        "bwl_m": bwl_m,
        "cb": cb,
        "cb_lmax": cb_lmax,
        "cwp": cwp,
        "bmt_m": bmt_m,
        "kmt_m": kb_m + bmt_m,
        "bml_m": bml_m,
        "kml_m": kb_m + bml_m,
        "wetted_m2": wetted_m2,
        "lcb_percent_L": (
            100.0 * lcb_m / length_m
            if length_m > 0.0
            else 0.0
        ),
        "lcf_percent_L": (
            100.0 * lcf_m / length_m
            if length_m > 0.0
            else 0.0
        ),
        "hydro_method": "solid_fallback"
    }



def calculate_hydrostatic_series(
    base_params,
    draft_values_m,
    density_t_per_m3,
    progress_callback=None,
    row_callback=None,
    continue_on_error=False
):
    """
    Dựng các surface vỏ một lần, mesh một lần, sau đó cắt tam giác theo từng
    mớn nước. Không yêu cầu closed Brep.
    """
    if not draft_values_m:
        return []

    closed_hull = None
    original_params = copy.deepcopy(base_params)

    try:
        closed_hull = create_hydrostatic_closed_hull(original_params)
        results = []
        total = len(draft_values_m)

        for index, draft_m in enumerate(draft_values_m):
            if progress_callback is not None:
                progress_callback(index + 1, total, draft_m)

            try:
                row = calculate_hydrostatic_at_draft(
                    closed_hull,
                    original_params,
                    draft_m,
                    density_t_per_m3
                )
            except Exception as error:
                if not continue_on_error:
                    raise
                row = {
                    "draft_m": float(draft_m),
                    "density_t_m3": float(density_t_per_m3),
                    "status": "INVALID",
                    "error_message": TEXT_TYPE(error)
                }
                Rhino.RhinoApp.WriteLine(
                    "Model 112 hydro T=%.3f m error: %s" %
                    (float(draft_m), str(error))
                )
            results.append(row)
            if row_callback is not None:
                row_callback(row, index + 1, total)
            Rhino.RhinoApp.Wait()

        return results
    finally:
        # generate_hull() cập nhật các biến global. Luôn trả chúng về đúng
        # bộ tham số Chế độ 1 sau khi tính, kể cả khi Boolean xảy ra lỗi.
        apply_parameter_bindings(
            copy.deepcopy(original_params)
        )


def format_hydrostatic_result(result):
    """Hiển thị một kết quả với nhãn và dấu hai chấm thẳng hàng."""
    if result is None:
        return u"Chưa có kết quả."
    if result.get("status") == "INVALID":
        return u"Chưa có số liệu tại T = %.3f m; xem chi tiết trong file Excel." % (
            float(result.get("draft_m", 0.0))
        )

    values = [
        (u"Mớn nước T", u"%.3f m" % result["draft_m"]),
        (u"Thể tích chiếm nước ∇/V", u"%.3f m³" % result["volume_m3"]),
        (u"Lượng chiếm nước Δ", u"%.3f t" % result["displacement_t"]),
        (u"LCB (từ X = 0)", u"%.3f m (%.2f %%L)" %
         (result["lcb_m"], result["lcb_percent_L"])),
        (u"TCB", u"%.4f m" % result["tcb_m"]),
        (u"KB (từ đường cơ bản)", u"%.3f m" % result["kb_m"]),
        (u"Diện tích đường nước Awp", u"%.3f m²" % result["awp_m2"]),
        (u"LCF (từ X = 0)", u"%.3f m (%.2f %%L)" %
         (result["lcf_m"], result["lcf_percent_L"])),
        (u"LWL", u"%.3f m" % result["lwl_m"]),
        (u"BWL", u"%.3f m" % result["bwl_m"]),
        (u"Hệ số béo khối Cb (WL)", u"%.4f" % result["cb"]),
        (u"Cb theo Lmax, Bmax", u"%.4f" % result.get("cb_lmax", 0.0)),
        (u"Hệ số diện tích Cwp", u"%.4f" % result["cwp"]),
        (u"BM ngang BMt", u"%.3f m" % result["bmt_m"]),
        (u"KM ngang KMt", u"%.3f m" % result["kmt_m"]),
        (u"BM dọc BML", u"%.3f m" % result["bml_m"]),
        (u"KM dọc KML", u"%.3f m" % result["kml_m"]),
        (u"Diện tích mặt ướt S", u"%.3f m²" % result["wetted_m2"]),
        (u"Khối lượng riêng ρ", u"%.4f t/m³" % result["density_t_m3"])
    ]
    label_width = max(len(name) for name, _ in values)
    return u"\n".join(
        name.ljust(label_width) + u" : " + value
        for name, value in values
    )




def sanitize_file_name_component(text_value):
    """
    Loại các ký tự không hợp lệ trong tên file Windows.
    """
    value = str(
        text_value
    )

    invalid_characters = [
        "<", ">", ":", '"',
        "/", "\\", "|", "?",
        "*"
    ]

    for character in invalid_characters:
        value = value.replace(
            character,
            "_"
        )

    return value.strip()


def build_default_hydro_csv_name(
    results,
    result_kind=None
):
    """
    Tạo tên mặc định có ý nghĩa để người dùng vẫn có thể sửa trong Save As.

    Ví dụ:
        Model112_thuytinh_T2.800m_20260824_0305.csv

    hoặc:
        Model112_thuytinh_T0.500-3.000m_6muc_20260824_0305.csv
    """
    now_text = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M"
    )

    if not results:
        return (
            "Model112_thuytinh_%s.csv" %
            now_text
        )

    if len(results) == 1:
        draft_value = float(
            results[0]["draft_m"]
        )

        name = (
            "Model112_thuytinh_T%.3fm_%s.csv" %
            (
                draft_value,
                now_text
            )
        )
    else:
        start_draft = float(
            results[0]["draft_m"]
        )

        end_draft = float(
            results[-1]["draft_m"]
        )

        name = (
            "Model112_thuytinh_T%.3f-%.3fm_%dmuc_%s.csv" %
            (
                start_draft,
                end_draft,
                len(results),
                now_text
            )
        )

    return sanitize_file_name_component(
        name
    )


def make_duplicate_safe_path(
    desired_path
):
    """
    Nếu file đã tồn tại hoặc đang bị ứng dụng khác giữ, tạo tên:
        ten_01.csv
        ten_02.csv
        ...

    Hàm chỉ tạo đường dẫn; không xóa/ghi đè file cũ.
    """
    folder = os.path.dirname(
        desired_path
    )

    base_name = os.path.basename(
        desired_path
    )

    root_name, extension = os.path.splitext(
        base_name
    )

    if not extension:
        extension = ".csv"

    for index in range(
        1,
        1000
    ):
        candidate = os.path.join(
            folder,
            "%s_%02d%s" %
            (
                root_name,
                index,
                extension
            )
        )

        if not os.path.exists(
            candidate
        ):
            return candidate

    # Fallback gần như không bao giờ xảy ra.
    timestamp = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    return os.path.join(
        folder,
        "%s_%s%s" %
        (
            root_name,
            timestamp,
            extension
        )
    )


def choose_hydro_csv_output_path(
    results,
    result_kind=None
):
    """
    Mở hộp thoại Save As của Rhino để:
    - chọn thư mục;
    - tự đặt tên;
    - đổi tên file trước khi xuất.

    Trả None nếu người dùng Cancel.
    """
    default_directory = (
        get_data_output_directory()
    )

    default_name = (
        build_default_hydro_csv_name(
            results,
            result_kind
        )
    )

    output_path = rs.SaveFileName(
        u"Lưu bảng thủy tĩnh CSV",
        u"CSV (*.csv)|*.csv||",
        default_directory,
        default_name,
        "csv"
    )

    if not output_path:
        return None

    root_name, extension = os.path.splitext(
        output_path
    )

    if not extension:
        output_path = (
            output_path +
            ".csv"
        )

    return output_path


HYDRO_EXPORT_FIELDS = (
    ("T_m", "draft_m"),
    ("V_m3", "volume_m3"),
    ("Delta_t", "displacement_t"),
    ("LCB_m", "lcb_m"),
    ("TCB_m", "tcb_m"),
    ("KB_m", "kb_m"),
    ("Awp_m2", "awp_m2"),
    ("LCF_m", "lcf_m"),
    ("LWL_m", "lwl_m"),
    ("BWL_m", "bwl_m"),
    ("Cb_WL", "cb"),
    ("Cb_LmaxBmax", "cb_lmax"),
    ("Cwp", "cwp"),
    ("BMt_m", "bmt_m"),
    ("KMt_m", "kmt_m"),
    ("BML_m", "bml_m"),
    ("KML_m", "kml_m"),
    ("S_wetted_m2", "wetted_m2"),
    ("rho_t_m3", "density_t_m3")
)


def hydro_export_data_rows(results):
    """A failed draft keeps its T value, but never receives fabricated numbers."""
    rows = []
    for item in results:
        invalid = item.get("status") == "INVALID"
        rows.append(tuple(
            item.get(key, "") if (not invalid or key == "draft_m") else ""
            for _, key in HYDRO_EXPORT_FIELDS
        ))
    return rows


def hydro_export_diagnostic_rows(results):
    """The same technical information as RC7, kept beneath the numeric table."""
    rows = []
    for item in results:
        status, detail = hydro_result_quality(item)
        if status == "VALID":
            continue
        rows.append((
            item.get("draft_m", ""), status,
            TEXT_TYPE(item.get("hydro_method", "")),
            item.get("closure_ratio", ""), detail
        ))
    return rows


def build_default_hydro_xlsx_name(results, result_kind=None):
    name = build_default_hydro_csv_name(results, result_kind)
    return os.path.splitext(name)[0] + ".xlsx"


def choose_hydro_xlsx_output_path(results, result_kind=None):
    output_path = rs.SaveFileName(
        u"Lưu bảng thủy tĩnh Excel",
        u"Excel Workbook (*.xlsx)|*.xlsx||",
        get_data_output_directory(),
        build_default_hydro_xlsx_name(results, result_kind),
        "xlsx"
    )
    if not output_path:
        return None
    if not TEXT_TYPE(output_path).lower().endswith(".xlsx"):
        output_path += ".xlsx"
    return output_path


def write_hydrostatic_xlsx(file_path, results):
    """One real .xlsx: numeric table, five empty rows, technical diagnostics."""
    if not results:
        raise Exception(u"Chưa có kết quả thủy tĩnh để xuất.")
    headers = [name for name, _ in HYDRO_EXPORT_FIELDS]
    last_column = xlsx_column_letter(len(headers) - 1)
    data_rows = hydro_export_data_rows(results)
    diagnostic_rows = hydro_export_diagnostic_rows(results)
    last_data_row = 3 + len(data_rows)
    # Five completely blank Excel rows between the table and this heading.
    diagnostic_title_row = last_data_row + 6
    diagnostic_header_row = diagnostic_title_row + 1
    last_row = diagnostic_header_row + max(1, len(diagnostic_rows))

    rows_xml = [
        u'<row r="1" ht="28" customHeight="1">%s</row>' %
        xlsx_inline_cell_xml(1, 0, u"MODEL 112 - BẢNG THỦY TĨNH", 1),
        u'<row r="2" ht="22" customHeight="1">%s</row>' %
        xlsx_inline_cell_xml(2, 0,
            u"Đơn vị: m, m², m³, t; mỗi mớn nước được tính độc lập.", 2)
    ]
    rows_xml.append(u'<row r="3" ht="30" customHeight="1">%s</row>' %
                    u"".join(xlsx_inline_cell_xml(3, i, label, 3)
                             for i, label in enumerate(headers)))
    for index, values in enumerate(data_rows):
        excel_row = 4 + index
        cells = []
        for column, value in enumerate(values):
            style = 5 if column in (10, 11, 12) else 4
            if value == "" or value is None or not is_finite_number(value):
                cells.append(xlsx_empty_cell_xml(excel_row, column, style))
            else:
                cells.append(xlsx_number_cell_xml(excel_row, column,
                                                   value, style))
        rows_xml.append(u'<row r="%d">%s</row>' %
                        (excel_row, u"".join(cells)))

    rows_xml.append(u'<row r="%d" ht="25" customHeight="1">%s</row>' %
                    (diagnostic_title_row,
                     xlsx_inline_cell_xml(diagnostic_title_row, 0,
                         u"CHI TIẾT KIỂM TRA - %d/%d mức cần đối chiếu" %
                         (len(diagnostic_rows), len(results)), 6)))
    diag_headers = (u"T (m)", u"Trạng thái", u"Phương pháp",
                    u"Closure", u"Ghi chú kỹ thuật")
    rows_xml.append(u'<row r="%d" ht="25" customHeight="1">%s</row>' %
                    (diagnostic_header_row,
                     u"".join(xlsx_inline_cell_xml(diagnostic_header_row,
                               i, label, 7) for i, label in
                               enumerate(diag_headers))))
    if not diagnostic_rows:
        row_index = diagnostic_header_row + 1
        rows_xml.append(u'<row r="%d">%s</row>' %
                        (row_index, xlsx_inline_cell_xml(row_index, 4,
                         u"Không có ghi chú kiểm tra ở các mức đã tính.", 8)))
    for index, (draft, status, method, closure, detail) in enumerate(
            diagnostic_rows):
        row_index = diagnostic_header_row + index + 1
        cells = [xlsx_number_cell_xml(row_index, 0, draft, 4),
                 xlsx_inline_cell_xml(row_index, 1, status,
                                      10 if status == "INVALID" else 9),
                 xlsx_inline_cell_xml(row_index, 2, method, 8)]
        if closure != "" and closure is not None and is_finite_number(closure):
            cells.append(xlsx_number_cell_xml(row_index, 3, closure, 5))
        cells.append(xlsx_inline_cell_xml(row_index, 4, detail, 8))
        rows_xml.append(u'<row r="%d" ht="52" customHeight="1">%s</row>' %
                        (row_index, u"".join(cells)))

    merge_ranges = [u"A1:%s1" % last_column,
                    u"A2:%s2" % last_column,
                    u"A%d:%s%d" % (diagnostic_title_row, last_column,
                                     diagnostic_title_row),
                    u"E%d:%s%d" % (diagnostic_header_row, last_column,
                                     diagnostic_header_row)]
    for row_index in range(diagnostic_header_row + 1, last_row + 1):
        merge_ranges.append(u"E%d:%s%d" % (row_index, last_column,
                                             row_index))
    merge_xml = u'<mergeCells count="%d">%s</mergeCells>' % (
        len(merge_ranges),
        u"".join(u'<mergeCell ref="%s"/>' % value
                 for value in merge_ranges)
    )
    sheet_xml = (u'<?xml version="1.0" encoding="UTF-8"?>'
        u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        u'<dimension ref="A1:%s%d"/>'
        u'<sheetViews><sheetView workbookViewId="0">'
        u'<pane ySplit="3" topLeftCell="A4" activePane="bottomLeft" state="frozen"/>'
        u'</sheetView></sheetViews><sheetFormatPr defaultRowHeight="19"/>'
        u'<cols><col min="1" max="1" width="12" customWidth="1"/>'
        u'<col min="2" max="%d" width="16" customWidth="1"/></cols>'
        u'<sheetData>%s</sheetData>%s'
        u'<autoFilter ref="A3:%s%d"/>'
        u'<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" '
        u'header="0.2" footer="0.2"/>'
        u'<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        u'</worksheet>') % (last_column, last_row, len(headers),
                            u"".join(rows_xml), merge_xml,
                            last_column, last_data_row)

    styles_xml = u'''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="0.000"/><numFmt numFmtId="165" formatCode="0.0000"/></numFmts>
<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="15"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF173856"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFE8B0"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFCBCB"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="3" fillId="2" borderId="1" xfId="0" applyFill="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="3" fillId="2" borderId="1" xfId="0" applyFill="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFill="1"/>
<xf numFmtId="0" fontId="2" fillId="4" borderId="1" xfId="0" applyFill="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    workbook_xml = u'''<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="THUY TINH" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    workbook_rels = u'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    package_rels = u'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    content_types = u'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
    directory = os.path.dirname(file_path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    archive = zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED)
    try:
        for name, content in [
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", package_rels),
            ("xl/workbook.xml", workbook_xml),
            ("xl/_rels/workbook.xml.rels", workbook_rels),
            ("xl/styles.xml", styles_xml),
            ("xl/worksheets/sheet1.xml", sheet_xml)
        ]:
            archive.writestr(name, content.encode("utf-8"))
    finally:
        archive.close()
    return file_path


def export_hydrostatic_results_xlsx(results, output_path=None):
    if not results:
        raise Exception(u"Chưa có kết quả thủy tĩnh để xuất.")
    desired = output_path or os.path.join(
        get_data_output_directory(), build_default_hydro_xlsx_name(results))
    actual = make_duplicate_safe_path(desired) if os.path.exists(desired) else desired
    renamed = actual != desired
    try:
        write_hydrostatic_xlsx(actual, results)
        return actual, renamed
    except (IOError, OSError):
        alternate = make_duplicate_safe_path(desired)
        try:
            write_hydrostatic_xlsx(alternate, results)
            return alternate, True
        except (IOError, OSError):
            fallback = os.path.join(get_data_output_directory(),
                                    build_default_hydro_xlsx_name(results))
            fallback = (make_duplicate_safe_path(fallback)
                        if os.path.exists(fallback) else fallback)
            write_hydrostatic_xlsx(fallback, results)
            return fallback, True


def export_hydrostatic_results(
    results,
    output_path=None
):
    """
    Xuất bảng thủy tĩnh ra CSV.

    - không còn bắt buộc ghi đè model_112_hydrostatics.csv;
    - cho phép truyền đường dẫn Save As;
    - nếu file bị Excel khóa, tự tạo tên mới an toàn.
    """
    if not results:
        raise Exception(
            u"Chưa có kết quả thủy tĩnh để xuất."
        )

    rows = [tuple(name for name, _ in HYDRO_EXPORT_FIELDS)]
    rows.extend(hydro_export_data_rows(results))
    # Keep diagnostics in the same Excel-readable CSV, five rows below results.
    rows.extend([tuple()] * 5)
    rows.append((u"CHI TIẾT KIỂM TRA",))
    rows.append(("T_m", "Trang_thai", "Phuong_phap", "Closure", "Ghi_chu"))
    rows.extend(hydro_export_diagnostic_rows(results))

    if not output_path:
        output_path = os.path.join(
            get_data_output_directory(),
            build_default_hydro_csv_name(
                results
            )
        )

    output_directory = os.path.dirname(
        output_path
    )

    if output_directory and not os.path.isdir(
        output_directory
    ):
        os.makedirs(
            output_directory
        )

    try:
        write_csv_file(
            output_path,
            rows
        )

        return (
            output_path,
            False
        )

    except (IOError, OSError) as error:
        # Có thể do file đang mở trong Excel hoặc thư mục không có quyền ghi.
        alternate_path = make_duplicate_safe_path(
            output_path
        )

        try:
            write_csv_file(
                alternate_path,
                rows
            )

            return (
                alternate_path,
                True
            )

        except Exception:
            # Nếu cả thư mục người dùng chọn cũng không ghi được, quay về
            # Model112_Data/AppData thay vì làm chương trình crash.
            fallback_path = os.path.join(
                get_data_output_directory(),
                build_default_hydro_csv_name(
                    results,
                    "fallback"
                )
            )

            fallback_path, renamed = write_csv_file_safe(
                fallback_path,
                rows,
                True
            )

            return (
                fallback_path,
                True
            )




# MODULE 14: GIAO DIỆN ETO - BA CHẾ ĐỘ
# Chế độ 1: tạo và điều chỉnh một vỏ tàu.
# Chế độ 4: khảo sát beta x alpha, kế thừa các tham số còn lại từ Chế độ 1.
# Chế độ 3: tính thủy tĩnh trên đúng hình dáng hiện tại của Chế độ 1.


def format_hydrostatic_report_table(results):
    """Numeric table only; leave a failed draft blank rather than showing zero."""
    if not results:
        return u"Chưa có dữ liệu thủy tĩnh."

    headers = [
        u"T(m)", u"V(m3)", u"Delta(t)", u"LCB(m)", u"KB(m)",
        u"Awp(m2)", u"LCF(m)", u"LWL(m)", u"BWL(m)",
        u"Cb(WL)", u"Cwp", u"BMt(m)", u"KMt(m)", u"S(m2)"
    ]
    keys = [
        "draft_m", "volume_m3", "displacement_t", "lcb_m", "kb_m",
        "awp_m2", "lcf_m", "lwl_m", "bwl_m", "cb", "cwp",
        "bmt_m", "kmt_m", "wetted_m2"
    ]
    display_rows = []
    for result in results:
        row = []
        for key in keys:
            if result.get("status") == "INVALID" and key != "draft_m":
                row.append(u"")
            elif key not in result or not is_finite_number(result[key]):
                row.append(u"")
            else:
                row.append((u"%.4f" if key in ("cb", "cwp") else u"%.3f") %
                           float(result[key]))
        display_rows.append(row)

    widths = model112_table_column_widths(headers, display_rows)
    separator = model112_table_separator(widths)
    lines = [model112_table_text_row(headers, widths, header=True), separator]
    lines.extend(model112_table_text_row(row, widths) for row in display_rows)
    lines.append(separator)
    return u"\n".join(lines)


def format_survey_matrix_preview(beta_values, alpha_values):
    """
    Hiển thị nhanh ma trận beta x alpha để người dùng thấy toàn bộ
    cấu hình khảo sát trước khi tạo mẫu.
    """
    if not beta_values or not alpha_values:
        return u"Chưa có ma trận khảo sát."

    headers = [u"α \\ β"] + [u"%.1f°" % v for v in beta_values]
    rows = [[u"%.1f°" % alpha] + [u"×"] * len(beta_values)
            for alpha in alpha_values]
    widths = model112_table_column_widths(headers, rows, minimum=7)
    lines = [
        model112_table_text_row(headers, widths, header=True),
        model112_table_separator(widths)
    ]
    lines.extend(model112_table_text_row(row, widths) for row in rows)

    lines.append(
        u"\nTổng số mẫu: %d x %d = %d" %
        (
            len(beta_values),
            len(alpha_values),
            len(beta_values) * len(alpha_values)
        )
    )

    return u"\n".join(lines)


def build_hull_parameter_signature(params):
    """
    Tạo chữ ký trạng thái để phát hiện bảng Hydro khảo sát đã cũ
    sau khi người dùng thay đổi tham số ở Trang 1.

    Chỉ dùng trong phiên chạy hiện tại, không lưu ra file.
    """
    items = []

    try:
        keys = sorted(
            params.__dict__.keys()
        )
    except Exception:
        return TEXT_TYPE(
            params
        )

    for key in keys:
        try:
            value = getattr(
                params,
                key
            )

            if isinstance(
                value,
                (list, tuple)
            ):
                normalized = tuple(
                    [
                        TEXT_TYPE(item)
                        for item in value
                    ]
                )
            else:
                normalized = TEXT_TYPE(
                    value
                )

            items.append(
                (
                    TEXT_TYPE(key),
                    normalized
                )
            )
        except Exception:
            items.append(
                (
                    TEXT_TYPE(key),
                    u"<unavailable>"
                )
            )

    return tuple(
        items
    )


def get_survey_hydro_display_header():
    """
    MODEL 112 V19
    Cột hiển thị trên giao diện và cột xuất file dùng CHUNG một định nghĩa.
    Nhờ đó file chạy ra có cùng thứ tự và tên cột với bảng trên giao diện.
    """
    return (
        u"Mẫu",
        u"beta",
        u"alpha",
        u"T(m)",
        u"V(m3)",
        u"Delta(t)",
        u"LCB(m)",
        u"KB(m)",
        u"Awp(m2)",
        u"LCF(m)",
        u"LWL(m)",
        u"BWL(m)",
        u"Cb",
        u"Cwp",
        u"S(m2)",
        u"TT"
    )


def get_survey_hydro_display_values(item):
    """
    Trả về ĐÚNG các chuỗi dùng để hiển thị/xuất:
      beta, alpha : 1 số lẻ
      T và các đại lượng hình học/thủy tĩnh : 3 số lẻ
      Cb, Cwp : 4 số lẻ
      dấu thập phân luôn là '.'
    """
    status = item.get(
        "status",
        "OK"
    )

    sample_text = TEXT_TYPE(
        int(
            item.get(
                "sample_index",
                0
            )
        )
    )

    beta_text = (
        "%.1f" %
        float(
            item.get(
                "beta_deg",
                0.0
            )
        )
    )

    alpha_text = (
        "%.1f" %
        float(
            item.get(
                "alpha_deg",
                0.0
            )
        )
    )

    draft_text = (
        "%.3f" %
        float(
            item.get(
                "draft_m",
                0.0
            )
        )
    )

    if status not in ("OK", "VALID", "WARNING"):
        error_text = TEXT_TYPE(
            item.get(
                "error_message",
                u"Lỗi không xác định"
            )
        )

        return (
            sample_text,
            beta_text,
            alpha_text,
            draft_text,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            u"ERROR: " + error_text
        )

    return (
        sample_text,
        beta_text,
        alpha_text,
        draft_text,
        "%.3f" % float(item.get("volume_m3", 0.0)),
        "%.3f" % float(item.get("displacement_t", 0.0)),
        "%.3f" % float(item.get("lcb_m", 0.0)),
        "%.3f" % float(item.get("kb_m", 0.0)),
        "%.3f" % float(item.get("awp_m2", 0.0)),
        "%.3f" % float(item.get("lcf_m", 0.0)),
        "%.3f" % float(item.get("lwl_m", 0.0)),
        "%.3f" % float(item.get("bwl_m", 0.0)),
        "%.4f" % float(item.get("cb", 0.0)),
        "%.4f" % float(item.get("cwp", 0.0)),
        "%.3f" % float(item.get("wetted_m2", 0.0)),
        (status + (u": " + TEXT_TYPE(item.get("diagnostic_message", ""))
                   if item.get("diagnostic_message") else ""))
    )


def format_survey_hydro_report_table(results):
    """
    Bảng xem nhanh Hydro của ma trận beta x alpha tại MỘT mớn nước.

    MODEL 112 V19:
    - giao diện và file export lấy dữ liệu từ cùng
      get_survey_hydro_display_values()
    - không có hai bộ quy tắc làm tròn khác nhau.
    """
    if not results:
        return u"Chưa có dữ liệu thủy tĩnh của mẫu khảo sát."

    headers = get_survey_hydro_display_header()
    display_rows = []
    long_notes = []
    ok_count = 0
    error_count = 0

    for item in results:
        values = list(get_survey_hydro_display_values(item))
        status = item.get("status", "OK")
        if status in ("OK", "VALID", "WARNING"):
            ok_count += 1
        else:
            error_count += 1
        if len(TEXT_TYPE(values[-1])) > 48:
            long_notes.append((values[0], TEXT_TYPE(values[-1])))
            values[-1] = TEXT_TYPE(values[-1])[:47] + u"…"
        display_rows.append(values)

    widths = model112_table_column_widths(headers, display_rows)
    separator = model112_table_separator(widths)
    lines = [model112_table_text_row(headers, widths, header=True), separator]
    lines.extend(
        model112_table_text_row(row, widths, left_indices=(len(widths) - 1,))
        for row in display_rows
    )
    lines.append(separator)
    lines.append(
        u"Tổng: %d | Thành công: %d | Lỗi: %d" %
        (
            len(results),
            ok_count,
            error_count
        )
    )
    for sample_index, note in long_notes:
        lines.append(u"Mẫu %s – chi tiết: %s" % (sample_index, note))

    return u"\n".join(
        lines
    )


def write_survey_hydro_display_csv(
    file_path,
    results
):
    """
    Xuất bảng đúng như dữ liệu hiển thị trên giao diện.

    Quy ước V19:
    - delimiter = ','
    - decimal = '.'
    - thêm dòng Excel 'sep=,' để Excel luôn tách đúng cột,
      không phụ thuộc Regional Settings của Windows.
    - UTF-8 BOM đúng một lần.
    - cùng header, thứ tự cột, số chữ số thập phân với giao diện.
    """
    import codecs

    rows = [
        get_survey_hydro_display_header()
    ]

    for item in results:
        rows.append(
            get_survey_hydro_display_values(
                item
            )
        )

    output_lines = [
        u"sep=,"
    ]

    for row in rows:
        escaped = []

        for value in row:
            text_value = TEXT_TYPE(
                value
            ).replace(
                '"',
                '""'
            )

            escaped.append(
                u'"' +
                text_value +
                u'"'
            )

        output_lines.append(
            u",".join(
                escaped
            )
        )

    content = (
        u"\r\n".join(
            output_lines
        ) +
        u"\r\n"
    )

    with open(
        file_path,
        "wb"
    ) as output_file:
        output_file.write(
            codecs.BOM_UTF8
        )

        output_file.write(
            content.encode(
                "utf-8"
            )
        )


def write_survey_hydro_display_csv_safe(
    desired_path,
    results,
    avoid_overwrite=True
):
    actual_path = desired_path
    renamed = False

    if (
        avoid_overwrite and
        os.path.exists(
            actual_path
        )
    ):
        actual_path = make_duplicate_safe_path(
            actual_path
        )
        renamed = True

    try:
        write_survey_hydro_display_csv(
            actual_path,
            results
        )

        return (
            actual_path,
            renamed
        )

    except (IOError, OSError):
        alternate_path = make_duplicate_safe_path(
            desired_path
        )

        write_survey_hydro_display_csv(
            alternate_path,
            results
        )

        return (
            alternate_path,
            True
        )

def build_survey_hydro_csv_name(
    results
):
    now_text = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    draft_m = 0.0

    if results:
        draft_m = float(
            results[0].get(
                "draft_m",
                0.0
            )
        )

    return sanitize_file_name_component(
        (
            "Model112_khaosat_hydro_T%.3fm_%dmau_%s.csv"
        ) %
        (
            draft_m,
            len(results),
            now_text
        )
    )


def choose_survey_hydro_csv_output_path(
    results
):
    default_directory = (
        get_data_output_directory()
    )

    default_name = (
        build_survey_hydro_csv_name(
            results
        )
    )

    output_path = rs.SaveFileName(
        u"Lưu bảng thủy tĩnh khảo sát CSV",
        u"CSV (*.csv)|*.csv||",
        default_directory,
        default_name,
        "csv"
    )

    if not output_path:
        return None

    root_name, extension = os.path.splitext(
        output_path
    )

    if not extension:
        output_path = (
            output_path +
            ".csv"
        )

    return output_path


def export_survey_hydro_results(
    results,
    output_path=None
):
    """
    MODEL 112 V20

    File xuất chính giống bảng Hydro đang hiển thị:
    Mẫu | beta | alpha | T | V | Delta | LCB | KB | Awp | LCF |
    LWL | BWL | Cb | Cwp | S | TT

    Không xuất lại 31 cột RAW vào bảng chính.
    Các giá trị dùng chung hàm format với giao diện.
    """
    if not results:
        raise Exception(
            u"Chưa có kết quả Hydro khảo sát để xuất."
        )

    if not output_path:
        output_path = os.path.join(
            get_data_output_directory(),
            build_survey_hydro_csv_name(
                results
            )
        )

    output_directory = os.path.dirname(
        output_path
    )

    if (
        output_directory and
        not os.path.isdir(
            output_directory
        )
    ):
        os.makedirs(
            output_directory
        )

    try:
        actual_path, renamed = (
            write_survey_hydro_display_csv_safe(
                output_path,
                results,
                True
            )
        )

        return (
            actual_path,
            renamed
        )

    except Exception:
        fallback_path = os.path.join(
            get_data_output_directory(),
            build_survey_hydro_csv_name(
                results
            )
        )

        actual_path, renamed = (
            write_survey_hydro_display_csv_safe(
                fallback_path,
                results,
                True
            )
        )

        return (
            actual_path,
            True
        )




# =============================================================================
# HƯỚNG DẪN THAM SỐ TRÊN GIAO DIỆN
# =============================================================================
# Nội dung dưới đây chỉ phục vụ giải thích ký hiệu và ảnh hưởng hình học.
# Không tham gia vào bất kỳ phép dựng hình hoặc phép tính thủy tĩnh nào.


PARAMETER_GUIDANCE_TEXT = {
    "Research": (
        u"β – Góc vát đáy tại vùng thân giữa (độ)\n"
        u"• Là góc deadrise dùng để điều khiển độ chữ V của đáy tại vùng thân giữa.\n"
        u"• Tăng β: đáy có xu hướng chữ V rõ hơn, các điểm đáy phía mạn được nâng cao hơn so với vùng sống tàu.\n"
        u"• Giảm β: đáy có xu hướng phẳng hơn. Thay đổi β làm thay đổi mặt cắt ngang và có thể ảnh hưởng thể tích chiếm nước, diện tích mặt ướt và các đặc trưng thủy tĩnh.\n\n"

        u"α – Góc nghiêng sống mũi (độ)\n"
        u"• Điều khiển độ nghiêng của sống mũi theo mặt phẳng dọc tâm.\n"
        u"• Trong mô hình, độ chạy ngang của sống mũi được xác định theo ΔX = ΔZ·tan(α).\n"
        u"• Tăng α: đoạn sống mũi chạy ngang dài hơn, điểm bắt đầu vùng sống mũi lùi về phía đuôi và dáng mũi nghiêng hơn.\n"
        u"• Giảm α: sống mũi đứng hơn và vùng chuyển tiếp mũi ngắn hơn.\n\n"

        u"Nchine – Số đường gãy góc mỗi mạn\n"
        u"• Xác định số đường đặc trưng trung gian giữa sống tàu và mép boong.\n"
        u"• 1: Lower Chine; 2: thêm Upper Inner; 3: thêm Upper Outer.\n"
        u"• Số đường lớn hơn cho phép mô tả mặt cắt phức tạp hơn nhưng làm topology và quá trình kiểm tra mép mặt phức tạp hơn.\n\n"
        u"Liên kết β mũi/đuôi theo β\n"
        u"• Bật: βT và βB tự nhận cùng giá trị với β vùng thân giữa.\n"
        u"• Tắt: βT và βB được phép chỉnh độc lập.\n"
        u"• Trong Trang 4 – Khảo sát mẫu, β mũi/đuôi vẫn giữ theo cấu hình của Trang 1; Trang 4 chỉ thay β giữa tàu và α.\n\n"
        u"Tạo nửa mạn – chỉ mạn phải / Starboard\n"
        u"• Bật: Chế độ 1 chỉ tạo phần Y ≥ 0; Chế độ 4 tạo các mẫu nửa mạn; Chế độ 2 chỉ giữ nửa Station/Waterline phía Starboard.\n"
        u"• Tắt: tạo đầy đủ Port + Starboard. Chế độ 3 thủy tĩnh luôn dựng lại đủ hai mạn để kết quả không bị chia đôi.\n\n"

        u"Lưu ý: β và α là hai biến chính dùng trong Trang 4 – Khảo sát mẫu. "
        u"Góc vát đáy tại mũi và tại đuôi được đặt riêng ở mục Hình dáng nâng cao."
    ),

    "Dimensions": (
        u"Lmax – Chiều dài lớn nhất của tàu (m)\n"
        u"• Là kích thước chính theo trục X của mô hình.\n"
        u"• Tăng Lmax làm thân tàu kéo dài theo phương dọc, thay đổi vị trí các sườn và khoảng chuyển tiếp mũi/đuôi theo tỷ lệ hình học.\n\n"

        u"Bmax – Chiều rộng lớn nhất của tàu (m)\n"
        u"• Là bề rộng cực đại theo phương Y; nửa rộng cơ sở của chương trình bằng Bmax/2.\n"
        u"• Tăng Bmax làm các đường chine và mép boong mở rộng theo phương ngang; giảm Bmax làm thân tàu thon hơn.\n\n"

        u"H – Chiều cao lớn nhất (m)\n"
        u"• Là thang chiều cao chính của mô hình tính từ đường cơ bản đến cao độ lớn nhất của thân tàu.\n"
        u"• Nhiều cao độ sống mũi, đường gãy và mép boong được xác định theo tỷ lệ của H.\n"
        u"• Tăng H làm các cao độ hình học liên quan tăng theo; giảm H làm thân tàu thấp hơn.\n\n"

        u"Bk – Chiều rộng keel (m)\n"
        u"• Là chiều rộng toàn phần của dải keel phẳng. Bk > 0 tạo hai mép keel và một dải mặt keel giữa chúng.\n"
        u"• Bk = 0: không tạo dải keel phẳng; hai panel đáy gặp nhau tại mặt phẳng dọc tâm.\n\n"
        u"T – Chiều chìm thiết kế (m)\n"
        u"• Xác định cao độ đường nước thiết kế: ZWL = Zbaseline + T.\n"
        u"• T không trực tiếp làm thay đổi các mặt vỏ khô; nó xác định phần chìm dùng cho đường nước tham chiếu và tính thủy tĩnh.\n"
        u"• Điều kiện bắt buộc: 0 < T < H."
    ),

    "Chine and Sheer": (
        u"ZB – Cao độ đầu đường gãy dưới tại mũi (m)\n"
        u"• Xác định vị trí đường gãy dưới nhập vào vùng sống mũi. Tăng ZB làm đầu đường gãy kết thúc cao hơn.\n\n"

        u"kB,LC – Tỷ lệ nửa rộng đường gãy dưới\n"
        u"• So sánh nửa rộng lớn nhất của lower chine với Bmax/2. Tăng hệ số làm đường gãy dưới mở rộng ra mạn.\n\n"

        u"kT,LC – Độ đầy đường gãy dưới tại đuôi\n"
        u"• Điều chỉnh bề rộng lower chine ở vùng vách đuôi. Giảm hệ số làm đáy đuôi gọn hơn; tăng hệ số làm phần đuôi đầy hơn theo phương ngang.\n\n"

        u"kZ,UC – Tỷ lệ cao đường gãy trên\n"
        u"• Xác định cao độ upper chine theo tỷ lệ của H. Tăng hệ số đưa đường gãy trên lên cao hơn.\n\n"

        u"kK,UC – Mức đường gãy trên đi theo sống tàu\n"
        u"• Điều khiển mức cao độ upper chine chịu ảnh hưởng bởi độ nâng của keel. Giá trị nhỏ làm upper chine ổn định/phẳng hơn theo phương dọc; giá trị lớn làm nó đi theo biến thiên của keel nhiều hơn.\n\n"

        u"ΔZ, ΔY – Khoảng lệch đứng và ngang của đường gãy ngoài\n"
        u"• ΔZ tăng: rail ngoài được nâng cao hơn. ΔY tăng: rail ngoài mở rộng ra mạn hơn.\n"
        u"• Hai đại lượng này tạo bề rộng và chiều cao cho dải upper chine phía ngoài.\n\n"

        u"ksheer – Tỷ lệ độ võng mép boong\n"
        u"• Điều khiển độ võng của đường sheer theo chiều dọc. Tăng giá trị làm biến thiên cao độ đường mép boong rõ hơn.\n\n"

        u"kB,sheer – Tỷ lệ nửa rộng lớn nhất mép boong\n"
        u"• Xác định mức mở rộng của sheer so với Bmax/2. Giá trị gần 1,0 làm mép boong tiến gần bề rộng cực đại."
    ),

    "Advanced": (
        u"βT – Góc vát đáy tại đuôi (độ)\n"
        u"• Điều khiển góc deadrise cục bộ ở vùng đuôi.\n"
        u"• Tăng βT làm tiết diện đáy đuôi chữ V rõ hơn; giảm βT làm đáy đuôi phẳng hơn.\n\n"

        u"βB – Góc vát đáy tại mũi (độ)\n"
        u"• Điều khiển góc deadrise cục bộ ở vùng mũi trước khi chuyển vào sống mũi.\n"
        u"• Tăng βB làm phần đáy mũi sâu/chữ V hơn; giảm βB làm đáy mũi mở phẳng hơn.\n\n"


        u"γT – Góc nghiêng vách đuôi (độ)\n"
        u"• Điều khiển độ nghiêng của transom theo mặt phẳng dọc.\n"
        u"• Khi tăng γT, điểm giao phía dưới của vách đuôi dịch về phía trước theo hình học, làm vách đuôi nghiêng rõ hơn."
    ),

    "Method": (
        u"Ns – Số sườn thân\n"
        u"• Là số mặt cắt chính dùng để dựng phần thân tàu, phạm vi 3–15.\n"
        u"• Tăng Ns giúp mô tả biến thiên dọc thân bằng nhiều section hơn nhưng làm số lượng dữ liệu và thời gian dựng tăng.\n"
        u"• Số sườn lớn không đồng nghĩa bề mặt luôn trơn hơn; độ trơn còn phụ thuộc phân bố section và hình dạng các rail dọc.\n\n"

        u"Nbf – Số mặt cắt làm trơn mũi\n"
        u"• Là số section bổ sung tại vùng chuyển tiếp từ thân chính vào sống mũi, phạm vi 2–5.\n"
        u"• Tăng Nbf cho nhiều điều kiện điều khiển hơn tại vùng mũi; quá nhiều section gần nhau có thể làm bề mặt nhạy với biến thiên hình học.\n\n"

        u"Nguyên tắc dựng bề mặt\n"
        u"• Các dải mặt ưu tiên dùng hai rail dọc (keel/chine/sheer) kết hợp các section ngang.\n"
        u"• Những dải kề nhau ưu tiên dùng chung rail để giảm sai lệch biên hình học.\n"
        u"• Mục này điều chỉnh mật độ section; không thay đổi trực tiếp kích thước chính Lmax, Bmax, H và T."
    )
}


DISPLAY_GUIDANCE_TEXT = (
    u"Keel – đường biên sống đáy\n"
    u"• Hiện các curve Keel của hai phía sống đáy. Các đường này nằm trong MODEL112::HULL_LINES::Keel và được Trang 2 dùng cho Hình đứng/Hình bằng.\n\n"

    u"Chine – đường gãy góc\n"
    u"• Hiện toàn bộ các chine đang hoạt động trên cả hai mạn: Chine dưới, Chine trên và các chine bổ sung nếu số đường gãy lớn hơn 3.\n"
    u"• Mỗi loại chine được lưu ở sublayer riêng trong MODEL112::HULL_LINES::Chines.\n\n"

    u"Sheer – đường mép boong\n"
    u"• Hiện hai đường Sheer chạy dọc mép boong. Đây cũng là đường biên trên của các panel mạn và là thành phần của bản vẽ đường hình 2D.\n\n"

    u"Station – sườn/mặt cắt chính\n"
    u"• Hiện các section ngang chính được dùng để dựng surface thân tàu. Đây là khung dựng, khác với Station được tạo riêng trong Trang 2 cho lines plan.\n\n"

    u"Bow fairing sections – mặt cắt làm trơn vùng mũi\n"
    u"• Hiện các section bổ sung giữa thân chính và sống mũi. Chúng phục vụ quá trình dựng/fairing bề mặt và không mặc định đưa vào Body Plan.\n\n"

    u"Design points – điểm hình học\n"
    u"• Hiện các điểm nguồn dùng để tạo keel, chine, sheer và section. Chỉ nên bật khi kiểm tra hình học vì số lượng điểm khá nhiều.\n\n"

    u"DWL – đường nước thiết kế\n"
    u"• Hiện đường/mặt tham chiếu tại Z = Zbaseline + T. Đây là đường nước thiết kế của Trang 1, không phải tập Waterline của Trang 2.\n\n"
    u"Khung vách đuôi\n"
    u"• Tạo các đường level ngang của vách đuôi và các biên Port/Starboard. Khi bật nửa mạn, khung chỉ giữ Centerline → Starboard và biên Starboard.\n"
    u"• Khung nằm trong MODEL112::TRANSOM_FRAME, tách khỏi layer khung dựng chung.\n\n"

    u"Bề mặt đầu ra\n"
    u"• 'Tạo các bề mặt vỏ tàu' tạo các panel thân; 'Tạo bề mặt vách đuôi' tạo transom; 'Tạo mặt boong' tạo mặt boong nếu cần.\n\n"

    u"Tổ chức đối tượng\n"
    u"• Khi giữ mặt vỏ rời, từng panel có thể chọn và kiểm tra độc lập.\n"
    u"• Tùy chọn nhóm chỉ group khung dựng; Keel/Chine/Sheer và các mặt tàu vẫn độc lập để phục vụ kiểm tra và bản vẽ 2D.\n\n"

    u"Xuất dữ liệu\n"
    u"• CSV tham số lưu bộ thông số đầu vào; CSV sườn lưu bảng StationRecord dùng trong quá trình dựng vỏ."
)



SURVEY_GUIDANCE_TEXT = (
    u"Nguyên tắc khảo sát β × α\n"
    u"• β là góc vát đáy tại vùng thân giữa; α là góc nghiêng sống mũi.\n"
    u"• Mỗi giá trị β tạo một cột; mỗi giá trị α tạo một hàng của ma trận khảo sát.\n"
    u"• Tổng số mẫu N = Nβ × Nα và được giới hạn tối đa 100 mẫu (10 × 10).\n\n"
    u"Tham số nền\n"
    u"• Mỗi mẫu được sao chép từ bộ tham số mới nhất của Trang 1: Lmax, Bmax, H, T, các đường gãy, sheer, vách đuôi, số sườn và cấu hình dựng mặt.\n"
    u"• Trong khảo sát chỉ β vùng thân giữa và α được thay đổi theo ma trận.\n"
    u"• β tại mũi và β tại đuôi không tự chạy theo β khảo sát; chúng giữ giá trị đã đặt ở Trang 1.\n\n"
    u"Ảnh hưởng cần theo dõi\n"
    u"• Thay β chủ yếu làm thay đổi dạng mặt cắt đáy và góc chữ V.\n"
    u"• Thay α chủ yếu làm thay đổi độ nghiêng và chiều dài chuyển tiếp của sống mũi.\n"
    u"• Có thể dùng các mẫu tạo ra để so sánh hình dáng, thể tích chiếm nước, LCB, KB, diện tích mặt ướt và các hệ số thủy tĩnh khi cần.\n\n"
    u"Thủy tĩnh cho ma trận khảo sát\n"
    u"• Tất cả mẫu dùng chung MỘT mớn nước T khảo sát; không chạy dải nhiều mớn nước trong Trang 4.\n"
    u"• Có thể dùng T thiết kế của Trang 1 hoặc nhập một T khảo sát riêng.\n"
    u"• Chương trình tính tuần tự từng mẫu: dựng nguồn vỏ tạm → tính Hydro → giải phóng nguồn tạm → chuyển sang mẫu tiếp theo.\n"
    u"• Không cần giữ 100 nguồn Hydro trong bộ nhớ cùng lúc. Mô hình 3D khảo sát và phép tính Hydro là hai chức năng độc lập.\n"
    u"• Kết quả có thể xuất CSV tương thích Excel, gồm beta, alpha, T và các đại lượng thủy tĩnh của từng mẫu.\n\n"
    u"Phân tích kết quả\n"
    u"• Mỗi mẫu được gắn trạng thái VALID / WARNING / INVALID. Nội dung chi tiết nêu loại lỗi, khu vực và gợi ý kiểm tra; trạng thái không dùng màu để thay thế nội dung.\n"
    u"• Sau khi tạo ma trận 3D, chương trình tính độ biến dạng hình học so với mẫu nền của Trang 1 bằng RMS và Dmax trên các điểm tương ứng Keel/Chine/Sheer.\n"
    u"• Báo cáo hình học còn kiểm tra sai lệch góc β đo lại trên tiết diện gần giữa tàu và góc α đo từ các điểm đầu-cuối sống mũi khi dữ liệu phù hợp.\n"
    u"• Biểu đồ Heatmap kết quả là lưới ô màu như trên poster: hàng β, cột α, từng ô ghi giá trị V/LCB hoặc đại lượng đã chọn.\n"
    u"• Chọn từ 2 giá trị β và 2 giá trị α để thấy lưới hai chiều; 1 β × 5 α chỉ tạo một hàng gồm 5 ô. Tính Hydro trước khi xem V/LCB; tạo mẫu 3D trước khi xem DRMS.\n"
    u"• Nút Xuất biểu đồ PNG lưu ảnh cho poster; Xuất lưới Excel lưu .xlsx có số thật, màu và bảng trạng thái để tiếp tục phân tích.\n"
    u"• Mẫu VALID/WARNING vẫn giữ số liệu trong CSV; INVALID ghi lý do. Bảng DRMS/Dmax có nút xuất CSV riêng.\n"
    u"• Nút Chồng tiết diện cắt Brep thật ở x/L = 0,25; 0,50; 0,75; 0,85. Giữ một góc cố định để xem góc còn lại làm hình dạng thay đổi; tạo ma trận 3D trước.\n"
    u"• Sai lệch β được đo ở sườn gần giữa tàu nhất và đối chiếu với góc cục bộ tại x/L ghi trong bảng. Sai lệch α đo trên đường sống mũi; dấu - nghĩa là không lấy được phép đo."
)


HYDRO_GUIDANCE_TEXT = (
    u"T – Mớn nước tính toán (m)\n"
    u"• Xác định mặt phẳng cắt phần chìm. Có thể dùng T thiết kế từ Trang 1 hoặc nhập một mớn nước riêng.\n\n"
    u"ρ – Khối lượng riêng của nước (t/m³)\n"
    u"• Dùng để tính lượng chiếm nước theo Δ = ρ·V. Giá trị 1,025 t/m³ thường được dùng cho nước biển trong bài toán thiết kế sơ bộ.\n\n"
    u"Nhiều mớn nước\n"
    u"• Tập mớn nước dùng T(i) = T0 + i·ΔT, với số mức N nhập trực tiếp; mặc định N = 7.\n"
    u"• T0 có thể bằng 0.000 m. V20 vẫn thực hiện phép cắt hình học tại Baseline; chỉ trả 0 khi thực sự không có phần chìm.\n\n"
    u"Các đại lượng kết quả\n"
    u"• V hoặc ∇ (m³): thể tích chiếm nước.\n"
    u"• Δ (t): lượng chiếm nước.\n"
    u"• LCB, TCB, KB (m): tọa độ tâm nổi theo phương dọc, ngang và đứng.\n"
    u"• Awp (m²): diện tích mặt đường nước; LCF (m): tâm diện tích mặt đường nước theo phương dọc.\n"
    u"• LWL, BWL (m): chiều dài và chiều rộng đường nước.\n"
    u"• Cb(T) = V/(LWL·BWL·T), được tính riêng tại từng mớn nước. Cb theo Lmax·Bmax chỉ giữ nội bộ để đối chiếu, không phải kết quả chính.\n"
    u"• Cwp = Awp/(LWL·BWL).\n"
    u"• BMt, KMt: bán kính tâm nghiêng và cao độ metacenter ngang.\n"
    u"• BML, KML: bán kính tâm nghiêng và cao độ metacenter dọc.\n"
    u"• S (m²): diện tích mặt ướt; ưu tiên Brep/NURBS đã Split theo mặt nước, mesh chỉ dùng khi Split thất bại.\n"
    u"• Engine V20 dùng tích phân signed tetrahedron cho V/LCB/TCB/KB, waterline Brep-Plane cho Awp/LCF/LWL/BWL và lưu closure ratio để chẩn đoán độ khép kín số học.\n\n"
    u"Lưu ý\n"
    u"• Kết quả phụ thuộc trực tiếp vào hình học vỏ tại thời điểm tính. Khi thay đổi tham số ở Trang 1, cần tính lại để cập nhật bảng thủy tĩnh.\n"
    u"• File Excel đặt chi tiết kiểm tra kỹ thuật dưới bảng số liệu, cách 5 hàng trống. Cần đối chiếu các ghi chú kỹ thuật trước khi dùng kết quả."
)



LINESPLAN_GUIDANCE_TEXT = (
    u"Sườn lý thuyết – Station (X = const)\n"
    u"• V20 mặc định Sườn 0 tại X = 0. Khi không bật Spacing tùy chỉnh, các mặt phẳng cắt được chia đều từ X=0 đến X=Lmax. "
    u"Khi bật Spacing, vị trí được xác định bởi X(i) = X0 + i·ΔX.\n\n"

    u"Đường nước – Waterline (Z = const)\n"
    u"• V20 mặc định ĐN0 tại Z - BaselineZ = 0. Khi chia tự động, ΔZ = H/N và các đường tiếp theo tăng đều; "
    u"đường cuối không bị ép đúng Z=H để tránh giao tuyến suy biến. Khi bật Spacing, dùng Z(i) = Z0 + i·ΔZ.\n\n"

    u"Đường cắt dọc – CD / Buttock (Y = const)\n"
    u"• V20 mặc định CD0 tại mặt phẳng dọc tâm Y = 0. Khi chia tự động, ΔY = (Bmax/2)/N và các CD tiếp theo tăng đều; "
    u"đường cuối không bị ép đúng Bmax/2. Khi bật Spacing, dùng Y(i) = Y0 + i·ΔY. Phiên bản V20 tạo CD ở một nửa mạn.\n\n"

    u"Spacing – kiểm soát vị trí\n"
    u"• Bật Spacing tùy chỉnh để đặt vị trí đường đầu tiên và khoảng cách giữa các đường. "
    u"Số lượng N vẫn được giữ nguyên, vì vậy đường thứ i có vị trí Start + i×Spacing. "
    u"Nút Tính spacing đều sẽ tự tính lại X0/ΔX, Z0/ΔZ và Y0/ΔY từ Lmax, Bmax, H và số lượng hiện tại.\n\n"

    u"Tổ chức layer\n"
    u"• Nguồn đường cắt 3D luôn được gom cố định vào bốn layer: Station (Sườn), Waterline (DN), Buttock (CD) và HullLine.\n"
    u"• Không còn sublayer riêng cho từng STA / WL / CD. Toàn bộ Keel/Chine/Sheer/Transom sao chép phục vụ đường hình cũng nằm chung trong HullLine.\n\n"
    u"Make2D tự động\n"
    u"• Hình đứng: trục ngang = chiều dài X, trục đứng = chiều cao Z; chiều rộng Y bị loại bỏ khi chiếu. "
    u"Hình bằng dùng World Top nhìn từ trên xuống: trục ngang = chiều dài X, trục đứng = chiều rộng Y; chiều cao Z bị loại bỏ. "
    u"Hình cạnh: trục ngang = chiều rộng/nửa chiều rộng Y, trục đứng = chiều cao Z; chiều dài X bị loại bỏ. "
    u"Station / Waterline / Buttock được đưa vào các hình chiếu để tạo lưới đường hình; HullLine, bao gồm Transom, được dùng ở cả hình đứng, hình bằng và Body Plan. "
    u"Toàn bộ kết quả nằm chung trong MODEL112::LINES_PLAN::DRAWING_2D.\n\n"

    u"Bảng tọa độ\n"
    u"• V20 đo trực tiếp trên KHUNG 3D SOURCE_3D, không đo trên Make2D. "
    u"Quy ước: X = chiều dài; nửa chiều rộng = |Y| từ Centerline Y=0; chiều cao = Z - BaselineZ và có thể âm. "
    u"Có kiểm tra tự động |Y| ≤ Bmax/2 và chiều cao ≤ H; nếu vượt giới hạn chương trình dừng xuất để tránh bảng sai.\n\n"

    u"Khuyến nghị thử nghiệm\n"
    u"• Bắt đầu với khoảng 11 sườn, 7 đường nước và 5 CD. "
    u"Trước tiên bấm 'Tạo đường cắt 3D' để kiểm tra các giao tuyến nằm đúng trên vỏ; "
    u"sau đó mới bấm 'Tạo bản vẽ 2D tự động'."
)




def build_guidance_panel(title_text, body_text, height=220):
    panel = forms.DynamicLayout()
    panel.Padding = drawing.Padding(8)
    panel.Spacing = drawing.Size(6, 6)

    title = forms.Label(
        Text=title_text
    )
    title.Font = drawing.Font(
        title.Font.Family,
        10,
        drawing.FontStyle.Bold
    )

    body = forms.TextArea()
    body.ReadOnly = True
    body.Wrap = True
    body.Height = height
    body.Text = body_text

    panel.AddRow(title)
    panel.Add(body, yscale=True)

    return panel




def v20_point_distance_components(point_a, point_b, units):
    dx = (float(point_a.X)-float(point_b.X))/units
    dy = (float(point_a.Y)-float(point_b.Y))/units
    dz = (float(point_a.Z)-float(point_b.Z))/units
    return dx,dy,dz,math.sqrt(dx*dx+dy*dy+dz*dz)


def v20_expected_deadrise_at(params, x_ratio):
    """Góc deadrise cục bộ theo quy luật của tham số gốc tại vị trí sườn đo."""
    mid_x = float(params.deadrise_midship_x_ratio)
    bow_x = float(params.bow_body_start_ratio)
    x = max(0.0, min(float(x_ratio), bow_x))
    if x <= mid_x:
        t = x / mid_x if mid_x > 0.0 else 1.0
        start = float(params.deadrise_stern_angle)
        end = float(params.deadrise_midship_angle)
    else:
        t = (x - mid_x) / (bow_x - mid_x) if bow_x > mid_x else 1.0
        start = float(params.deadrise_midship_angle)
        end = float(params.deadrise_bow_angle)
    t = max(0.0, min(1.0, t))
    blend = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    return start + (end - start) * blend


def v20_actual_alpha_from_keel(object_ids, params, transform):
    """Đo góc từ hai điểm hình học trên đường keel đã tạo trong Rhino."""
    stem_x = DerivedHullData(params).stem_start_x
    expected = rg.Point3d(stem_x, 0.5 * float(params.keel_width),
                          float(params.depth) * float(params.c_height_ratio))
    expected.Transform(transform)
    for object_id in object_ids:
        if object_full_layer_path(object_id) != LAYER_HULL_KEEL:
            continue
        obj = sc.doc.Objects.FindId(object_id)
        if obj is None or not isinstance(obj.Geometry, rg.Curve):
            continue
        curve = obj.Geometry
        ok, parameter = curve.ClosestPoint(expected)
        if not ok:
            continue
        start = curve.PointAt(parameter)
        a = curve.PointAtStart
        b = curve.PointAtEnd
        tip = a if a.X > b.X else b
        dx = abs(float(tip.X) - float(start.X))
        dz = abs(float(tip.Z) - float(start.Z))
        if dz > 1e-9:
            return math.degrees(math.atan2(dx, dz))
    return None


def v20_geometry_metrics_from_station_records(reference_records, sample_records, sample_params):
    metrics = {
        "drms_m": 0.0, "dmax_m": 0.0,
        "dx_rms_m": 0.0, "dy_rms_m": 0.0, "dz_rms_m": 0.0,
        "beta_measured_deg": None, "beta_expected_deg": None,
        "beta_at_x_ratio": None, "beta_error_deg": None,
        "alpha_measured_deg": None, "alpha_error_deg": None
    }
    if not reference_records or not sample_records:
        return metrics
    units=float(sample_params.units_per_meter)
    pairs=[]
    attrs=("keel_point","lower_point","upper_inner_point","upper_outer_point","sheer_point")
    for r0,r1 in zip(reference_records,sample_records):
        for a in attrs:
            p0=getattr(r0,a,None); p1=getattr(r1,a,None)
            if p0 is not None and p1 is not None:
                pairs.append(v20_point_distance_components(p0,p1,units))
    if pairs:
        n=float(len(pairs))
        metrics["dx_rms_m"]=math.sqrt(sum(x[0]*x[0] for x in pairs)/n)
        metrics["dy_rms_m"]=math.sqrt(sum(x[1]*x[1] for x in pairs)/n)
        metrics["dz_rms_m"]=math.sqrt(sum(x[2]*x[2] for x in pairs)/n)
        metrics["drms_m"]=math.sqrt(sum(x[3]*x[3] for x in pairs)/n)
        metrics["dmax_m"]=max(x[3] for x in pairs)
    try:
        mid=min(sample_records,key=lambda r:abs(float(r.reference_x_ratio)-0.5))
        dy=abs(float(mid.lower_point.Y)-float(mid.keel_point.Y))
        dz=float(mid.lower_point.Z)-float(mid.keel_point.Z)
        if dy>1e-12:
            bm=math.degrees(math.atan2(dz,dy))
            metrics["beta_measured_deg"]=bm
            metrics["beta_at_x_ratio"]=float(mid.reference_x_ratio)
            expected=v20_expected_deadrise_at(sample_params, mid.reference_x_ratio)
            metrics["beta_expected_deg"]=expected
            metrics["beta_error_deg"]=abs(bm-expected)
    except Exception:
        pass
    return metrics


def v20_format_geometry_survey_table(results):
    if not results:
        return u"Chưa có dữ liệu hình học khảo sát."
    headers = [u"Mẫu", u"β", u"α", u"TT", u"DRMS(m)", u"Dmax(m)",
               u"Dx", u"Dy", u"Dz", u"x/L đo β", u"eβ(°)", u"eα(°)"]
    display_rows = []
    notes = []
    for r in results:
        def f(key,fmt="%.4f"):
            v=r.get(key,None)
            return u"-" if v is None else (fmt % float(v))
        status = TEXT_TYPE(r.get("status", ""))
        if len(status) > 14:
            notes.append((r.get("sample_index", 0), status))
            status = status[:13] + u"…"
        display_rows.append([
            u"%d" % int(r.get("sample_index", 0)),
            u"%.1f" % float(r.get("beta_deg", 0)),
            u"%.1f" % float(r.get("alpha_deg", 0)), status,
            f("drms_m"), f("dmax_m"), f("dx_rms_m"), f("dy_rms_m"),
            f("dz_rms_m"), f("beta_at_x_ratio", "%.3f"),
            f("beta_error_deg", "%.3f"), f("alpha_error_deg", "%.3f")
        ])
    widths = model112_table_column_widths(headers, display_rows)
    lines = [model112_table_text_row(headers, widths, header=True),
             model112_table_separator(widths)]
    lines.extend(
        model112_table_text_row(row, widths, left_indices=(3,))
        for row in display_rows
    )
    for sample_index, status in notes:
        lines.append(u"Mẫu %s – TT đầy đủ: %s" % (sample_index, status))
    return u"\n".join(lines)


def v20_collect_heatmap_data(beta_values, alpha_values, rows, metric_key):
    """Dữ liệu theo hàng β, cột α như lưới khảo sát trong poster."""
    lookup = {}
    values = []
    for row in rows or []:
        key = (round(float(row.get("beta_deg", 0.0)), 6),
               round(float(row.get("alpha_deg", 0.0)), 6))
        status = row.get("status", "VALID")
        value = row.get(metric_key)
        if status == "INVALID" or value is None:
            lookup[key] = (None, status)
            continue
        try:
            value = float(value)
            if not is_finite_number(value):
                lookup[key] = (None, status)
                continue
        except Exception:
            lookup[key] = (None, status)
            continue
        lookup[key] = (value, status)
        values.append(value)
    matrix = []
    for beta in beta_values:
        matrix.append([
            lookup.get((round(float(beta), 6), round(float(alpha), 6)),
                       (None, u"CHƯA TÍNH"))
            for alpha in alpha_values
        ])
    return matrix, (min(values), max(values)) if values else (None, None)


def v20_heatmap_rgb(value, low, high):
    """Một thang màu dùng chung cho giao diện, PNG và Excel."""
    if value is None or low is None:
        return (231, 235, 240), False
    ratio = 0.5 if high - low <= 1.0e-15 else (value - low) / (high - low)
    ratio = max(0.0, min(1.0, ratio))
    low_rgb = (52, 69, 146)
    mid_rgb = (65, 176, 153)
    high_rgb = (249, 218, 97)
    first, last, fraction = ((low_rgb, mid_rgb, ratio * 2.0)
                             if ratio <= 0.5 else
                             (mid_rgb, high_rgb, (ratio - 0.5) * 2.0))
    rgb = [int(round(first[i] + (last[i] - first[i]) * fraction))
           for i in range(3)]
    return tuple(rgb), ratio < 0.35


def v20_heatmap_color(value, low, high):
    rgb, white_text = v20_heatmap_rgb(value, low, high)
    return drawing.Color.FromArgb(*rgb), white_text


def v20_heatmap_cell(text, background, white_text=False, width=102):
    panel = forms.Panel()
    panel.Width = width
    panel.Height = 51
    panel.BackgroundColor = background
    label = forms.Label(Text=text)
    label.TextColor = (drawing.Color.FromArgb(255, 255, 255) if white_text
                       else drawing.Color.FromArgb(22, 43, 72))
    label.TextAlignment = forms.TextAlignment.Center
    label.Wrap = forms.WrapMode.Word
    content = forms.DynamicLayout()
    content.Padding = drawing.Padding(2, 7, 2, 2)
    content.AddRow(label)
    panel.Content = content
    return panel


def v20_build_heatmap_grid(beta_values, alpha_values, rows, metric_key, title):
    matrix, bounds = v20_collect_heatmap_data(
        beta_values, alpha_values, rows, metric_key)
    low, high = bounds
    layout = forms.DynamicLayout()
    layout.Padding = drawing.Padding(8)
    layout.Spacing = drawing.Size(2, 2)
    heading = forms.Label(Text=u"%s  |  Hàng: β (°)  •  Cột: α (°)" % title)
    layout.AddRow(heading)
    header = [v20_heatmap_cell(u"β \\ α", drawing.Color.FromArgb(205, 221, 238))]
    for alpha in alpha_values:
        header.append(v20_heatmap_cell(u"α = %.1f°" % float(alpha),
                                      drawing.Color.FromArgb(205, 221, 238)))
    layout.AddRow(*header)
    for beta, values in zip(beta_values, matrix):
        cells = [v20_heatmap_cell(u"β = %.1f°" % float(beta),
                                  drawing.Color.FromArgb(205, 221, 238))]
        for value, status in values:
            color, white_text = v20_heatmap_color(value, low, high)
            if value is None:
                cell_text = u"INVALID" if status == "INVALID" else u"—"
            else:
                cell_text = u"%.3f\n%s" % (value, status)
            cells.append(v20_heatmap_cell(cell_text, color, white_text))
        layout.AddRow(*cells)
    if low is None:
        layout.AddRow(forms.Label(Text=u"Chưa có số liệu %s. Hãy tính ma trận trước." % title))
    else:
        legend = [forms.Label(Text=u"Thấp  %.3f" % low)]
        for level in range(5):
            swatch = low + (high - low) * level / 4.0
            color, white_text = v20_heatmap_color(swatch, low, high)
            legend.append(v20_heatmap_cell(u" ", color, white_text, width=43))
        legend.append(forms.Label(Text=u"Cao  %.3f" % high))
        layout.AddRow(*legend)
        layout.AddRow(forms.Label(Text=u"Xanh lam: thấp → xanh lục → vàng: cao. Màu chỉ biểu thị giá trị số; VALID/WARNING hiển thị bằng chữ. Ô xám: INVALID hoặc chưa có kết quả."))
    return layout


def v20_heatmap_export_path(extension, metric_key):
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = "Model112_Heatmap_%s_%s.%s" % (metric_key, now, extension)
    path = rs.SaveFileName(
        u"Xuất biểu đồ lưới MODEL 112",
        (u"Ảnh PNG (*.png)|*.png||" if extension == "png"
         else u"Excel (*.xlsx)|*.xlsx||"),
        get_data_output_directory(), filename, extension)
    if not path:
        return None
    if not path.lower().endswith("." + extension):
        path += "." + extension
    return path


def v20_export_heatmap_xlsx(file_path, beta_values, alpha_values,
                            rows, metric_key, title):
    """Excel Open XML: lưới ô màu và ô số thật, không cần Excel COM."""
    matrix, bounds = v20_collect_heatmap_data(
        beta_values, alpha_values, rows, metric_key)
    low, high = bounds
    if low is None:
        raise Exception(u"Chưa có kết quả số cho đại lượng đã chọn.")

    sheet_rows = []
    total_cols = max(6, len(alpha_values) + 1)
    last_col = xlsx_column_letter(total_cols - 1)
    header = [xlsx_inline_cell_xml(4, 0, u"β \\ α", 2)]
    for col, alpha in enumerate(alpha_values, 1):
        header.append(xlsx_number_cell_xml(4, col, float(alpha), 2))
    sheet_rows.append(u'<row r="1" ht="30" customHeight="1">%s</row>' %
                      xlsx_inline_cell_xml(1, 0, u"MODEL 112 - HEATMAP %s" % title, 1))
    sheet_rows.append(u'<row r="2">%s</row>' %
                      xlsx_inline_cell_xml(2, 0, u"Hàng: góc β (độ) | Cột: góc α (độ)", 0))
    sheet_rows.append(u'<row r="3">%s</row>' %
                      xlsx_inline_cell_xml(3, 0,
                          u"Xanh lam: thấp → xanh lục → vàng: cao. Ô xám: INVALID hoặc chưa tính.", 0))
    sheet_rows.append(u'<row r="4">%s</row>' % u"".join(header))
    for row_idx, (beta, values) in enumerate(zip(beta_values, matrix), 5):
        cells = [xlsx_number_cell_xml(row_idx, 0, beta, 2)]
        for col_idx, (value, status) in enumerate(values, 1):
            if value is None:
                cells.append(xlsx_inline_cell_xml(
                    row_idx, col_idx,
                    u"INVALID" if status == "INVALID" else u"—", 3))
            else:
                level = (5 if high - low <= 1.0e-15 else
                         int(round(10.0 * (value - low) / (high - low))))
                cells.append(xlsx_number_cell_xml(
                    row_idx, col_idx, value, 4 + max(0, min(10, level))))
        sheet_rows.append(u'<row r="%d" ht="26" customHeight="1">%s</row>' %
                          (row_idx, u"".join(cells)))

    legend_row = 6 + len(beta_values)
    legend = [xlsx_inline_cell_xml(legend_row, 0, u"Thấp → Cao", 2)]
    for col in range(1, 6):
        fraction = (col - 1) / 4.0
        legend.append(xlsx_number_cell_xml(
            legend_row, col, low + (high - low) * fraction,
            4 + int(round(10.0 * fraction))))
    sheet_rows.append(u'<row r="%d">%s</row>' %
                      (legend_row, u"".join(legend)))
    status_title_row = legend_row + 2
    sheet_rows.append(u'<row r="%d">%s</row>' % (
        status_title_row, xlsx_inline_cell_xml(
            status_title_row, 0, u"TRẠNG THÁI TỪNG MẪU", 1)))
    status_header = [xlsx_inline_cell_xml(status_title_row + 1, 0, u"β \\ α", 2)]
    for col, alpha in enumerate(alpha_values, 1):
        status_header.append(xlsx_number_cell_xml(
            status_title_row + 1, col, alpha, 2))
    sheet_rows.append(u'<row r="%d">%s</row>' %
                      (status_title_row + 1, u"".join(status_header)))
    for row_idx, (beta, values) in enumerate(zip(beta_values, matrix),
                                              status_title_row + 2):
        cells = [xlsx_number_cell_xml(row_idx, 0, beta, 2)]
        for col_idx, (value, status) in enumerate(values, 1):
            cells.append(xlsx_inline_cell_xml(row_idx, col_idx, status,
                                               3 if value is None else 0))
        sheet_rows.append(u'<row r="%d">%s</row>' %
                          (row_idx, u"".join(cells)))
    last_row = status_title_row + 1 + len(beta_values)

    fills = [
        u'<fill><patternFill patternType="none"/></fill>',
        u'<fill><patternFill patternType="gray125"/></fill>'
    ]
    for color in [(20, 55, 96), (205, 221, 238), (231, 235, 240)]:
        fills.append(u'<fill><patternFill patternType="solid"><fgColor rgb="FF%02X%02X%02X"/><bgColor indexed="64"/></patternFill></fill>' % color)
    for level in range(11):
        rgb, _ = v20_heatmap_rgb(level, 0, 10)
        fills.append(u'<fill><patternFill patternType="solid"><fgColor rgb="FF%02X%02X%02X"/><bgColor indexed="64"/></patternFill></fill>' % rgb)
    xfs = [u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
           u'<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1"/>',
           u'<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFill="1"/>',
           u'<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1"/>']
    for level in range(11):
        _, white = v20_heatmap_rgb(level, 0, 10)
        xfs.append(u'<xf numFmtId="164" fontId="%d" fillId="%d" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1"/>' %
                   (1 if white else 2, 5 + level))
    styles_xml = u'''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="0.000"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>
<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>
<font><b/><color rgb="FF163452"/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="%d">%s</fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="%d">%s</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>''' % (len(fills), u"".join(fills), len(xfs), u"".join(xfs))
    sheet_xml = u'''<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<dimension ref="A1:%s%d"/><sheetViews><sheetView workbookViewId="0"/></sheetViews>
<sheetFormatPr defaultRowHeight="19"/><cols><col min="1" max="1" width="19" customWidth="1"/>
<col min="2" max="%d" width="17" customWidth="1"/></cols>
<sheetData>%s</sheetData><mergeCells count="4">
<mergeCell ref="A1:%s1"/><mergeCell ref="A2:%s2"/>
<mergeCell ref="A3:%s3"/><mergeCell ref="A%d:%s%d"/>
</mergeCells><pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
</worksheet>''' % (last_col, last_row, total_cols, u"".join(sheet_rows),
                   last_col, last_col, last_col,
                   status_title_row, last_col, status_title_row)
    workbook_xml = u'''<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Heatmap" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    workbook_rels = u'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    package_rels = u'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    content_types = u'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
    directory = os.path.dirname(file_path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    archive = zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED)
    try:
        for name, content in [
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", package_rels),
            ("xl/workbook.xml", workbook_xml),
            ("xl/_rels/workbook.xml.rels", workbook_rels),
            ("xl/styles.xml", styles_xml),
            ("xl/worksheets/sheet1.xml", sheet_xml)
        ]:
            archive.writestr(name, content.encode("utf-8"))
    finally:
        archive.close()
    return file_path


def v20_export_heatmap_png(file_path, beta_values, alpha_values,
                           rows, metric_key, title):
    """Xuất ảnh độc lập bằng System.Drawing đi kèm Rhino Windows."""
    matrix, bounds = v20_collect_heatmap_data(
        beta_values, alpha_values, rows, metric_key)
    low, high = bounds
    if low is None:
        raise Exception(u"Chưa có kết quả số cho đại lượng đã chọn.")
    sd = System.Drawing
    cell_w, cell_h = 112, 64
    left, top = 118, 132
    width = max(640, left + cell_w * len(alpha_values) + 48)
    height = max(365, top + cell_h * len(beta_values) + 112)
    bitmap = sd.Bitmap(width, height)
    graphics = sd.Graphics.FromImage(bitmap)
    font_title = sd.Font("Segoe UI", 18, sd.FontStyle.Bold)
    font_header = sd.Font("Segoe UI", 10, sd.FontStyle.Bold)
    font_number = sd.Font("Segoe UI", 11, sd.FontStyle.Bold)
    font_note = sd.Font("Segoe UI", 9)
    navy = sd.SolidBrush(sd.Color.FromArgb(21, 53, 88))
    gray_line = sd.Pen(sd.Color.FromArgb(200, 211, 225))
    try:
        graphics.Clear(sd.Color.White)
        graphics.DrawString(u"MODEL 112 - %s" % title,
                            font_title, navy, 32.0, 24.0)
        graphics.DrawString(u"Biểu đồ lưới β × α | Hàng: β (°) | Cột: α (°)",
                            font_note, navy, 32.0, 70.0)
        for col, alpha in enumerate(alpha_values):
            graphics.DrawString(u"α = %.1f°" % float(alpha), font_header,
                                navy, float(left + col * cell_w + 15), 103.0)
        for row_idx, (beta, values) in enumerate(zip(beta_values, matrix)):
            y = top + row_idx * cell_h
            graphics.DrawString(u"β = %.1f°" % float(beta), font_header,
                                navy, 15.0, float(y + 18))
            for col_idx, (value, status) in enumerate(values):
                x = left + col_idx * cell_w
                rgb, use_white = v20_heatmap_rgb(value, low, high)
                fill = sd.SolidBrush(sd.Color.FromArgb(*rgb))
                ink = sd.SolidBrush(sd.Color.White if use_white
                                    else sd.Color.FromArgb(22, 43, 72))
                try:
                    graphics.FillRectangle(fill, x, y, cell_w - 2, cell_h - 2)
                    graphics.DrawRectangle(gray_line, x, y, cell_w - 2, cell_h - 2)
                    if value is None:
                        label = u"INVALID" if status == "INVALID" else u"—"
                        graphics.DrawString(label, font_header, ink,
                                            float(x + 8), float(y + 18))
                    else:
                        graphics.DrawString(u"%.3f" % value, font_number, ink,
                                            float(x + 8), float(y + 7))
                        graphics.DrawString(status, font_note, ink,
                                            float(x + 8), float(y + 34))
                finally:
                    ink.Dispose()
                    fill.Dispose()
        legend_y = top + cell_h * len(beta_values) + 22
        graphics.DrawString(u"Thấp %.3f" % low, font_note, navy,
                            float(left), float(legend_y))
        for level in range(5):
            swatch = low + (high - low) * level / 4.0
            rgb, _ = v20_heatmap_rgb(swatch, low, high)
            fill = sd.SolidBrush(sd.Color.FromArgb(*rgb))
            try:
                graphics.FillRectangle(fill, left + 100 + level * 38,
                                       legend_y, 36, 17)
            finally:
                fill.Dispose()
        graphics.DrawString(u"Cao %.3f" % high, font_note, navy,
                            float(left + 305), float(legend_y))
        graphics.DrawString(
            u"Màu chỉ giá trị số; VALID/WARNING ghi bằng chữ. Ô xám: INVALID hoặc chưa tính.",
            font_note, navy, 32.0, float(legend_y + 34))
        directory = os.path.dirname(file_path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        graphics.Flush()
        graphics.Dispose()
        graphics = None
        bitmap.Save(file_path, sd.Imaging.ImageFormat.Png)
    finally:
        gray_line.Dispose()
        navy.Dispose()
        font_note.Dispose()
        font_number.Dispose()
        font_header.Dispose()
        font_title.Dispose()
        if graphics is not None:
            graphics.Dispose()
        bitmap.Dispose()
    return file_path



class Model112Form(forms.Form):
    def __init__(self):
        forms.Form.__init__(self)

        # IronPython không truyền ổn định object Python tùy chỉnh qua constructor .NET Eto.
        # Vì vậy Form dùng constructor không tham số rồi sao chép bộ tham số dùng chung vào self.params.
        self.params = copy.deepcopy(PARAMS)
        self.parameter_specs = (
            build_ui_parameter_specs(
                self.params
            )
        )
        self.parameter_controls = {}
        self.updating_controls = False

        # MODEL 112 V19 - trạng thái Bảng tọa độ của Chế độ 2.
        self.coordinate_extra_columns = []
        self.coordinate_table_data = None
        self.coordinate_feature_options = []
        self.coordinate_axis_options = [
            u"Y - Nửa chiều rộng",
            u"Z - Chiều cao"
        ]
        self.coordinate_unit_options = [
            u"mm",
            u"m"
        ]
        self._hidden_preview_final_ids = []
        self._hidden_linesplan_source_ids = list(
            sc.sticky.get(HIDDEN_LINESPLAN_SOURCE_STICKY_KEY, []) or []
        )

        self.Title = (
            u"Model 112 - Chương trình tạo vỏ tàu"
        )
               
        # Giao diện ba trang cần không gian ngang rộng để xem bảng và báo cáo.
        self.ClientSize = drawing.Size(
            1180,
            760
        )
        self.Resizable = True
        self.Padding = drawing.Padding(10)

        self.preview_timer = forms.UITimer()
        self.preview_timer.Interval = 0.40
        self.preview_timer.Elapsed += (
            self.on_preview_timer
        )

        self.live_preview_check = (
            forms.CheckBox(
                Text=u"Xem trước tự động"
            )
        )
        self.live_preview_check.Checked = False

        self.link_profile_check = (
            forms.CheckBox(
                Text=u"Liên kết góc vát đáy mũi và đuôi theo β"
            )
        )
        self.link_profile_check.Checked = (
            self.params.link_deadrise_profile
        )
        self.link_profile_check.CheckedChanged += (
            self.on_link_profile_changed
        )

        self.half_model_check = (
            forms.CheckBox(
                Text=u"Tạo nửa mạn - chỉ mạn phải / Starboard"
            )
        )
        self.half_model_check.Checked = bool(
            getattr(
                self.params,
                "create_half_model",
                False
            )
        )
        self.half_model_check.CheckedChanged += (
            self.on_half_model_changed
        )

        self.status_label = forms.Label(
            Text=u"Sẵn sàng"
        )
        self.diagnostic_label = forms.Label(
            Text=u"[VALID] Chưa có kiểm tra mới."
        )
        self.diagnostic_label.Wrap = forms.WrapMode.Word

        self.Content = self.build_content()

        self.Closed += self.on_closed

        if (
            self.params.create_half_model and
            int(self.main_pages.SelectedIndex) == 0
        ):
            self.hide_mode1_background(include_final=False)

        self.apply_link_profile_state()


    def load_parameters(self, params):
        self.params = copy.deepcopy(params)
        return self.params


    def build_content(self):
        """
        GIAO DIỆN BỐN TRANG RIÊNG.

        Không còn:
            ComboBox -> Visible/Hidden ba layout.

        Thay bằng:
            Trang 1 | Trang 2 | Trang 3 | Trang 4

        Mỗi trang chiếm toàn bộ vùng làm việc và luôn có tab điều hướng ở phía trên.
        Các trang vẫn dùng chung self.params nên tách giao diện nhưng KHÔNG tách dữ liệu.
        """
        root = forms.DynamicLayout()
        root.Spacing = drawing.Size(8, 8)

        # ------------------------------------------------------------------
        # HEADER GỌN - KHÔNG CHIẾM NHIỀU CHIỀU CAO.
        # ------------------------------------------------------------------
        title_label = forms.Label(
            Text=u"MODEL 112 - CHƯƠNG TRÌNH TẠO VỎ TÀU THAM SỐ"
        )
        title_label.Font = drawing.Font(
            title_label.Font.Family,
            15,
            drawing.FontStyle.Bold
        )

        self.document_summary_label = forms.Label(
            Text=(
                u"Document: %s"
            ) %
            document_unit_name()
        )
        self.document_summary_label.Wrap = forms.WrapMode.Word

        root.AddRow(title_label)
        root.AddRow(self.document_summary_label)

        # ------------------------------------------------------------------
        # TRANG 1 - TẠO VỎ TÀU.
        # Giữ các tab tham số con vì chúng hợp lý trong riêng trang thiết kế.
        # ------------------------------------------------------------------
        self.mode1_layout = forms.DynamicLayout()
        self.mode1_layout.Padding = drawing.Padding(6)
        self.mode1_layout.Spacing = drawing.Size(8, 8)

        self.tab_control = forms.TabControl()

        group_order = [
            ("Dimensions", u"Kích thước"),
            ("Research", u"Tham số khảo sát"),
            ("Chine and Sheer", u"Đường gãy & mép boong"),
            ("Advanced", u"Hình dáng nâng cao"),
            ("Method", u"Chỉnh trơn bề mặt")
        ]

        for group_key, page_text in group_order:
            page = forms.TabPage(Text=page_text)
            page.Content = self.build_parameter_page(
                group_key
            )
            self.tab_control.Pages.Add(
                page
            )

        display_page = forms.TabPage(
            Text=u"Hiển thị"
        )
        display_page.Content = (
            self.build_display_page()
        )
        self.tab_control.Pages.Add(
            display_page
        )

        self.mode1_layout.Add(
            self.tab_control,
            yscale=True
        )
        self.mode1_layout.AddRow(
            self.build_footer()
        )

        # ------------------------------------------------------------------
        # TRANG 2, 3 - MỖI TRANG DÙNG TOÀN BỘ KHÔNG GIAN.
        # ------------------------------------------------------------------
        self.mode2_layout = (
            self.build_survey_mode()
        )

        self.mode3_layout = (
            self.build_hydrostatic_mode()
        )

        self.mode4_layout = (
            self.build_linesplan_mode()
        )

        # ------------------------------------------------------------------
        # TAB ĐIỀU HƯỚNG CHÍNH.
        # ------------------------------------------------------------------
        self.main_pages = forms.TabControl()

        page_hull = forms.TabPage(
            Text=u"1. TẠO VỎ TÀU"
        )
        page_hull.Content = self.mode1_layout

        page_linesplan = forms.TabPage(
            Text=u"2. ĐƯỜNG HÌNH 2D"
        )
        page_linesplan.Content = self.mode4_layout

        page_hydro = forms.TabPage(
            Text=u"3. THỦY TĨNH"
        )
        page_hydro.Content = self.mode3_layout

        page_survey = forms.TabPage(
            Text=u"4. KHẢO SÁT MẪU β × α"
        )
        page_survey.Content = self.mode2_layout

        self.main_pages.Pages.Add(
            page_hull
        )
        self.main_pages.Pages.Add(
            page_linesplan
        )
        self.main_pages.Pages.Add(
            page_hydro
        )
        self.main_pages.Pages.Add(
            page_survey
        )

        requested_page = sc.sticky.get(
            START_PAGE_STICKY_KEY,
            0
        )
        try:
            requested_page = int(requested_page)
        except Exception:
            requested_page = 0
        requested_page = max(0, min(3, requested_page))

        self.main_pages.SelectedIndex = requested_page
        self.main_pages.SelectedIndexChanged += (
            self.on_mode_changed
        )

        root.Add(
            self.main_pages,
            yscale=True
        )

        # ------------------------------------------------------------------
        # FOOTER CHUNG.
        # ------------------------------------------------------------------
        close_button = forms.Button(
            Text=u"Đóng"
        )
        close_button.Click += (
            self.on_close_clicked
        )

        global_footer = forms.DynamicLayout()
        global_footer.Spacing = drawing.Size(
            8,
            0
        )
        global_footer.AddRow(
            self.diagnostic_label
        )
        global_footer.AddRow(
            self.status_label,
            None,
            close_button
        )
        root.AddRow(
            global_footer
        )

        return root


    def build_parameter_page(
        self,
        group_name
    ):
        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(8)
        layout.Spacing = drawing.Size(6, 6)

        if group_name == "Dimensions":
            layout.AddRow(
                self.half_model_check
            )
            layout.AddRow(None)

        if group_name == "Research":
            layout.AddRow(
                self.link_profile_check
            )
            layout.AddRow(
                None
            )

        matching_specs = [
            spec
            for spec in self.parameter_specs
            if spec.group == group_name
        ]

        for spec in matching_specs:
            layout.AddRow(
                self.build_parameter_row(
                    spec
                )
            )

        layout.AddRow(
            None
        )

        guidance_text = PARAMETER_GUIDANCE_TEXT.get(
            group_name,
            u""
        )

        if guidance_text:
            layout.Add(
                build_guidance_panel(
                    u"HƯỚNG DẪN THAM SỐ – KÝ HIỆU VÀ ẢNH HƯỞNG",
                    guidance_text,
                    250
                )
            )

        layout.AddRow(
            None
        )

        scroll = forms.Scrollable()
        scroll.Content = layout
        return scroll


    def build_parameter_row(
        self,
        spec
    ):
        label = forms.Label(
            Text=spec.label
        )
        label.Width = 205
        label.ToolTip = spec.tooltip

        numeric = forms.NumericStepper()
        numeric.Width = 105
        numeric.MinValue = spec.minimum
        numeric.MaxValue = spec.maximum
        numeric.Increment = spec.step
        numeric.DecimalPlaces = spec.decimals
        numeric.Value = self.get_display_value(
            spec
        )
        numeric.ToolTip = spec.tooltip

        slider = forms.Slider()
        slider.Width = 330
        slider.MinValue = 0
        slider.MaxValue = self.get_slider_max(
            spec
        )
        slider.Value = self.display_value_to_slider(
            spec,
            numeric.Value
        )
        slider.ToolTip = spec.tooltip

        unit_label = forms.Label(
            Text=spec.unit
        )
        unit_label.Width = 45

        self.parameter_controls[
            spec.key
        ] = {
            "spec": spec,
            "numeric": numeric,
            "slider": slider
        }

        numeric.ValueChanged += (
            lambda sender, event, key=spec.key:
            self.on_numeric_changed(
                key
            )
        )

        slider.ValueChanged += (
            lambda sender, event, key=spec.key:
            self.on_slider_changed(
                key
            )
        )

        row = forms.DynamicLayout()
        row.Spacing = drawing.Size(6, 0)
        row.AddRow(
            label,
            numeric,
            slider,
            unit_label
        )

        return row


    def build_display_page(self):
        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(12)
        layout.Spacing = drawing.Size(8, 8)

        self.show_keel_check = (
            forms.CheckBox(
                Text=u"Hiển thị Keel - các đường biên sống đáy"
            )
        )
        self.show_keel_check.Checked = bool(
            getattr(
                self.params,
                "show_keel_curve",
                self.params.show_longitudinal_curves
            )
        )

        self.show_chine_check = (
            forms.CheckBox(
                Text=u"Hiển thị Chine - toàn bộ đường gãy góc hai mạn"
            )
        )
        self.show_chine_check.Checked = bool(
            getattr(
                self.params,
                "show_chine_curves",
                self.params.show_longitudinal_curves
            )
        )

        self.show_sheer_check = (
            forms.CheckBox(
                Text=u"Hiển thị Sheer - đường mép boong hai mạn"
            )
        )
        self.show_sheer_check.Checked = bool(
            getattr(
                self.params,
                "show_sheer_curve",
                self.params.show_longitudinal_curves
            )
        )

        self.show_body_stations_check = (
            forms.CheckBox(
                Text=u"Hiển thị Station - các sườn/mặt cắt chính dùng dựng vỏ"
            )
        )
        self.show_body_stations_check.Checked = (
            self.params.show_body_stations
        )

        self.show_bow_sections_check = (
            forms.CheckBox(
                Text=u"Hiển thị Bow fairing sections - mặt cắt bổ sung làm trơn vùng mũi"
            )
        )
        self.show_bow_sections_check.Checked = (
            self.params.show_bow_fairing_sections
        )

        self.show_design_points_check = (
            forms.CheckBox(
                Text=u"Hiển thị Design points - các điểm hình học dùng dựng đường/mặt"
            )
        )
        self.show_design_points_check.Checked = (
            self.params.show_design_points
        )

        self.show_waterline_check = (
            forms.CheckBox(
                Text=u"Hiển thị DWL - đường nước thiết kế tại mớn nước T"
            )
        )
        self.show_waterline_check.Checked = (
            self.params.create_design_waterline
        )

        self.show_transom_frame_check = (
            forms.CheckBox(
                Text=u"Hiển thị khung vách đuôi - đường level và biên vách"
            )
        )
        self.show_transom_frame_check.Checked = bool(
            getattr(
                self.params,
                "show_transom_frame",
                True
            )
        )

        # Các tùy chọn bề mặt đầu ra đã có sẵn trong engine.
        self.create_hull_check = forms.CheckBox(
            Text=u"Tạo các bề mặt vỏ tàu"
        )
        self.create_hull_check.Checked = (
            self.params.create_hull_surfaces
        )

        self.create_transom_check = forms.CheckBox(
            Text=u"Tạo bề mặt vách đuôi"
        )
        self.create_transom_check.Checked = (
            self.params.create_transom_surfaces
        )

        self.create_deck_check = forms.CheckBox(
            Text=u"Tạo mặt boong"
        )
        self.create_deck_check.Checked = (
            self.params.create_deck_surface
        )

        # -------------------------------------------------------------
                                                     
        # -------------------------------------------------------------
        self.separate_surfaces_check = (
            forms.CheckBox(
                Text=u"Giữ các mặt vỏ rời để kiểm tra thủ công"
            )
        )
        self.separate_surfaces_check.Checked = (
            not bool(
                self.params.join_hull_surfaces
            )
        )

        self.group_framework_check = (
            forms.CheckBox(
                Text=u"Chỉ nhóm khung dựng; giữ Keel/Chine/Sheer và mặt tàu độc lập"
            )
        )
        self.group_framework_check.Checked = (
            bool(
                self.params.group_framework_only
            )
        )

        self.export_parameter_check = (
            forms.CheckBox(
                Text=u"Xuất bảng tham số CSV"
            )
        )
        self.export_parameter_check.Checked = (
            self.params.export_parameter_table
        )

        self.export_station_check = (
            forms.CheckBox(
                Text=u"Xuất bảng sườn CSV"
            )
        )
        self.export_station_check.Checked = (
            self.params.export_station_table
        )

        display_sections = [
            (
                u"ĐỐI TƯỢNG HIỂN THỊ",
                [
                    self.show_keel_check,
                    self.show_chine_check,
                    self.show_sheer_check,
                    self.show_body_stations_check,
                    self.show_bow_sections_check,
                    self.show_design_points_check,
                    self.show_waterline_check
                ]
            ),
            (
                u"VÁCH ĐUÔI",
                [
                    self.show_transom_frame_check,
                    self.create_transom_check
                ]
            ),
            (
                u"BỀ MẶT TẠO RA",
                [
                    self.create_hull_check,
                    self.create_deck_check
                ]
            ),
            (
                u"TỔ CHỨC VÀ XUẤT DỮ LIỆU",
                [
                    self.separate_surfaces_check,
                    self.group_framework_check,
                    self.export_parameter_check,
                    self.export_station_check
                ]
            )
        ]

        for section_title, controls in display_sections:
            section_label = forms.Label(
                Text=section_title
            )
            section_label.Font = drawing.Font(
                section_label.Font.Family,
                10,
                drawing.FontStyle.Bold
            )
            layout.AddRow(section_label)

            for control in controls:
                control.CheckedChanged += (
                    self.on_display_changed
                )
                layout.AddRow(
                    control
                )

            layout.AddRow(None)

        layout.AddRow(
            None
        )

        layout.Add(
            build_guidance_panel(
                u"HƯỚNG DẪN HIỂN THỊ VÀ ĐẦU RA",
                DISPLAY_GUIDANCE_TEXT,
                280
            )
        )

        layout.AddRow(
            None
        )

        scroll = forms.Scrollable()
        scroll.Content = layout
        return scroll



    def build_survey_mode(self):
        # ---------------------------------------------------------------------
        # CHẾ ĐỘ 4 - KHẢO SÁT TỰ ĐỘNG
        # Người dùng nhập trực tiếp tối đa 10 giá trị beta và 10 giá trị alpha.
        # Tổng số mẫu tối đa = 10 x 10 = 100.
        # Không sử dụng file CSV/TXT và không còn ma trận 25 mẫu cố định.
        # ---------------------------------------------------------------------
        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(12)
        layout.Spacing = drawing.Size(8, 8)

        heading = forms.Label(
            Text=u"CHẾ ĐỘ 4 - KHẢO SÁT MẪU TỰ ĐỘNG"
        )
        heading.Font = drawing.Font(
            heading.Font.Family,
            12,
            drawing.FontStyle.Bold
        )

        self.survey_base_summary = forms.Label(Text=u"")
        self.survey_base_summary.Wrap = forms.WrapMode.Word

        # Số lượng giá trị beta được dùng trong hàng nhập phía dưới.
        self.survey_beta_count = forms.NumericStepper()
        self.survey_beta_count.MinValue = 1
        self.survey_beta_count.MaxValue = 10
        self.survey_beta_count.Increment = 1
        self.survey_beta_count.DecimalPlaces = 0
        self.survey_beta_count.Value = 5
        self.survey_beta_count.Width = 75

        # Số lượng giá trị alpha được dùng trong hàng nhập phía dưới.
        self.survey_alpha_count = forms.NumericStepper()
        self.survey_alpha_count.MinValue = 1
        self.survey_alpha_count.MaxValue = 10
        self.survey_alpha_count.Increment = 1
        self.survey_alpha_count.DecimalPlaces = 0
        self.survey_alpha_count.Value = 5
        self.survey_alpha_count.Width = 75

        count_row = forms.DynamicLayout()
        count_row.Spacing = drawing.Size(8, 0)
        count_row.AddRow(
            forms.Label(Text=u"Số giá trị góc vát đáy β:"),
            self.survey_beta_count,
            forms.Label(Text=u"Số giá trị góc nghiêng mũi α:"),
            self.survey_alpha_count,
            None
        )

        # Các giá trị đầu tiên giữ preset nghiên cứu cũ để tiện bắt đầu,
        # nhưng người dùng có thể sửa trực tiếp từng ô và tăng/giảm số lượng.
        default_beta_values = (
            list(self.params.survey_default_deadrise_values) +
            [18.0, 21.0, 24.0, 27.0, 30.0]
        )
        default_alpha_values = (
            list(self.params.survey_default_bow_rake_values) +
            [28.0, 30.0, 33.0, 37.0, 41.0]
        )

        self.survey_beta_inputs = []
        self.survey_alpha_inputs = []

        beta_row = forms.DynamicLayout()
        beta_row.Spacing = drawing.Size(4, 0)
        alpha_row = forms.DynamicLayout()
        alpha_row.Spacing = drawing.Size(4, 0)

        beta_controls = []
        alpha_controls = []

        for index in range(10):
            beta_input = forms.NumericStepper()
            beta_input.Width = 62
            beta_input.MinValue = self.params.deadrise_slider_min
            beta_input.MaxValue = self.params.deadrise_slider_max
            beta_input.Increment = self.params.deadrise_slider_step
            beta_input.DecimalPlaces = 1
            beta_input.Value = default_beta_values[index]
            beta_input.ToolTip = u"Giá trị góc vát đáy β thứ %d" % (index + 1)
            beta_input.ValueChanged += self.on_survey_values_changed
            self.survey_beta_inputs.append(beta_input)
            beta_controls.append(beta_input)

            alpha_input = forms.NumericStepper()
            alpha_input.Width = 62
            alpha_input.MinValue = self.params.bow_rake_slider_min
            alpha_input.MaxValue = self.params.bow_rake_slider_max
            alpha_input.Increment = self.params.bow_rake_slider_step
            alpha_input.DecimalPlaces = 1
            alpha_input.Value = default_alpha_values[index]
            alpha_input.ToolTip = u"Giá trị góc nghiêng sống mũi α thứ %d" % (index + 1)
            alpha_input.ValueChanged += self.on_survey_values_changed
            self.survey_alpha_inputs.append(alpha_input)
            alpha_controls.append(alpha_input)

        beta_row.AddRow(*beta_controls)
        alpha_row.AddRow(*alpha_controls)

        self.survey_matrix_summary = forms.Label(Text=u"")
        self.survey_matrix_summary.Wrap = forms.WrapMode.Word

                                                    
        self.survey_matrix_preview = forms.TextArea()
        self.survey_matrix_preview.ReadOnly = True
        self.survey_matrix_preview.Wrap = False
        model112_set_table_font(self.survey_matrix_preview)
        self.survey_matrix_preview.Height = 250
        self.survey_matrix_preview.Text = u"Chưa có ma trận khảo sát."

        # -----------------------------------------------------------------
        # V19 - THỦY TĨNH CHO MA TRẬN KHẢO SÁT
        # Tất cả mẫu dùng chung MỘT mớn nước. Tính tuần tự, không giữ
        # nguồn Hydro của 100 mẫu cùng lúc.
        # -----------------------------------------------------------------
        self.survey_hydro_use_design_draft = forms.CheckBox(
            Text=u"Dùng chiều chìm T hiện tại của Chế độ 1"
        )
        self.survey_hydro_use_design_draft.Checked = True
        self.survey_hydro_use_design_draft.CheckedChanged += (
            self.on_survey_hydro_draft_mode_changed
        )

        self.survey_hydro_draft_input = forms.NumericStepper()
        self.survey_hydro_draft_input.Width = 105
        self.survey_hydro_draft_input.MinValue = 0.0
        self.survey_hydro_draft_input.MaxValue = max(
            0.001,
            float(
                self.params.depth /
                self.params.units_per_meter
            ) -
            0.001
        )
        self.survey_hydro_draft_input.Increment = 0.05
        self.survey_hydro_draft_input.DecimalPlaces = 3
        self.survey_hydro_draft_input.Value = (
            self.params.draft /
            self.params.units_per_meter
        )
        self.survey_hydro_draft_input.Enabled = False
        self.survey_hydro_draft_input.ValueChanged += (
            self.on_survey_hydro_setting_changed
        )

        self.survey_hydro_density_input = forms.NumericStepper()
        self.survey_hydro_density_input.Width = 100
        self.survey_hydro_density_input.MinValue = 0.50
        self.survey_hydro_density_input.MaxValue = 1.50
        self.survey_hydro_density_input.Increment = 0.001
        self.survey_hydro_density_input.DecimalPlaces = 4
        self.survey_hydro_density_input.Value = 1.025
        self.survey_hydro_density_input.ValueChanged += (
            self.on_survey_hydro_setting_changed
        )

        survey_hydro_input_row = forms.DynamicLayout()
        survey_hydro_input_row.Spacing = drawing.Size(8, 0)
        survey_hydro_input_row.AddRow(
            forms.Label(Text=u"Mớn nước T khảo sát:"),
            self.survey_hydro_draft_input,
            forms.Label(Text=u"m"),
            forms.Label(Text=u"Khối lượng riêng ρ:"),
            self.survey_hydro_density_input,
            forms.Label(Text=u"t/m³"),
            None
        )

        calculate_survey_hydro_button = forms.Button(
            Text=u"Tính thủy tĩnh ma trận"
        )
        calculate_survey_hydro_button.Width = 180
        calculate_survey_hydro_button.Click += (
            self.on_calculate_survey_hydro
        )

        cancel_survey_hydro_button = forms.Button(
            Text=u"Dừng"
        )
        cancel_survey_hydro_button.Width = 90
        cancel_survey_hydro_button.Click += (
            self.on_cancel_survey_hydro
        )

        export_survey_hydro_button = forms.Button(
            Text=u"Xuất Hydro CSV / Excel..."
        )
        export_survey_hydro_button.Width = 170
        export_survey_hydro_button.Click += (
            self.on_export_survey_hydro_csv
        )

        self.survey_hydro_summary = forms.Label(
            Text=u"Chưa tính thủy tĩnh cho ma trận khảo sát."
        )
        self.survey_hydro_summary.Wrap = forms.WrapMode.Word

        self.survey_hydro_report_area = forms.TextArea()
        self.survey_hydro_report_area.ReadOnly = True
        self.survey_hydro_report_area.Wrap = False
        model112_set_table_font(self.survey_hydro_report_area)
        self.survey_hydro_report_area.Height = 320
        self.survey_hydro_report_area.Text = (
            u"Chưa có dữ liệu Hydro khảo sát."
        )

        self.survey_hydro_results = []
        self.survey_hydro_signature = None
        self.survey_hydro_cancel_requested = False
        self.survey_geometry_results = []
        self.survey_geometry_signature = None
        self.survey_model_surfaces = {}

        self.survey_geometry_report_area = forms.TextArea()
        self.survey_geometry_report_area.ReadOnly = True
        self.survey_geometry_report_area.Wrap = False
        model112_set_table_font(self.survey_geometry_report_area)
        self.survey_geometry_report_area.Height = 230
        self.survey_geometry_report_area.Text = u"Chưa có dữ liệu hình học khảo sát."

        self.survey_heatmap_metric = forms.DropDown()
        self.survey_heatmap_metric.Width = 210
        self.survey_heatmap_metric.DataStore = [
            u"V - Thể tích chiếm nước",
            u"LCB - Tâm nổi dọc",
            u"KB - Cao độ tâm nổi",
            u"Awp - Diện tích đường nước",
            u"S - Diện tích mặt ướt",
            u"Cb - Hệ số béo",
            u"Cwp - Hệ số diện tích đường nước",
            u"BMt - Bán kính tâm nghiêng ngang",
            u"DRMS - Biến dạng hình học"
        ]
        self.survey_heatmap_metric.SelectedIndex = 0
        heatmap_button = forms.Button(Text=u"Cập nhật Heatmap")
        heatmap_button.Width = 150
        heatmap_button.Click += self.on_update_survey_heatmap
        heatmap_png_button = forms.Button(Text=u"Xuất PNG...")
        heatmap_png_button.Width = 120
        heatmap_png_button.Click += self.on_export_survey_heatmap_png
        heatmap_excel_button = forms.Button(Text=u"Xuất Excel...")
        heatmap_excel_button.Width = 120
        heatmap_excel_button.Click += self.on_export_survey_heatmap_excel
        self.survey_heatmap_area = forms.Scrollable()
        self.survey_heatmap_area.Height = 330
        self.survey_heatmap_area.Content = forms.Label(Text=u"Chưa có dữ liệu Heatmap.")
        self.survey_heatmap_metric.SelectedIndexChanged += self.on_update_survey_heatmap

        self.section_comparison_mode = forms.DropDown()
        self.section_comparison_mode.DataStore = [
            u"Thay β, giữ α", u"Thay α, giữ β"
        ]
        self.section_comparison_mode.SelectedIndex = 0
        self.section_comparison_mode.Width = 220
        self.section_fixed_alpha = forms.NumericStepper()
        self.section_fixed_alpha.MinValue = self.params.bow_rake_slider_min
        self.section_fixed_alpha.MaxValue = self.params.bow_rake_slider_max
        self.section_fixed_alpha.Increment = 1
        self.section_fixed_alpha.DecimalPlaces = 1
        self.section_fixed_alpha.Value = 35.0
        self.section_fixed_alpha.Width = 75
        self.section_fixed_beta = forms.NumericStepper()
        self.section_fixed_beta.MinValue = self.params.deadrise_slider_min
        self.section_fixed_beta.MaxValue = self.params.deadrise_slider_max
        self.section_fixed_beta.Increment = 1
        self.section_fixed_beta.DecimalPlaces = 1
        self.section_fixed_beta.Value = 7.0
        self.section_fixed_beta.Width = 75
        overlay_button = forms.Button(Text=u"Chồng tiết diện")
        overlay_button.Width = 150
        overlay_button.Click += self.on_overlay_survey_sections
        clear_overlay_button = forms.Button(Text=u"Xóa tiết diện")
        clear_overlay_button.Width = 130
        clear_overlay_button.Click += self.on_clear_survey_sections
        self.section_overlay_report = forms.Label(Text=u"Tạo ma trận 3D trước khi chồng tiết diện.")
        self.section_overlay_report.Wrap = forms.WrapMode.Word

        export_geometry_button = forms.Button(Text=u"Xuất hình học CSV...")
        export_geometry_button.Width = 160
        export_geometry_button.Click += self.on_export_survey_geometry_csv

        generate_button = forms.Button(
            Text=u"Tạo ma trận mẫu"
        )
        generate_button.Width = 150
        generate_button.Click += self.on_generate_survey

        clear_button = forms.Button(
            Text=u"Xóa ma trận"
        )
        clear_button.Width = 120
        clear_button.Click += self.on_clear_survey

        survey_model_button_row = forms.StackLayout()
        survey_model_button_row.Orientation = forms.Orientation.Horizontal
        survey_model_button_row.Spacing = 8
        survey_model_button_row.Items.Add(forms.StackLayoutItem(generate_button))
        survey_model_button_row.Items.Add(forms.StackLayoutItem(clear_button))

        geometry_export_row = forms.StackLayout()
        geometry_export_row.Orientation = forms.Orientation.Horizontal
        geometry_export_row.Spacing = 8
        geometry_export_row.Items.Add(forms.StackLayoutItem(export_geometry_button))

        section_control_row = forms.StackLayout()
        section_control_row.Orientation = forms.Orientation.Horizontal
        section_control_row.Spacing = 8
        section_control_row.Items.Add(forms.StackLayoutItem(forms.Label(Text=u"β cố định:")))
        section_control_row.Items.Add(forms.StackLayoutItem(self.section_fixed_beta))
        section_control_row.Items.Add(forms.StackLayoutItem(forms.Label(Text=u"α cố định:")))
        section_control_row.Items.Add(forms.StackLayoutItem(self.section_fixed_alpha))
        section_control_row.Items.Add(forms.StackLayoutItem(forms.Label(Text=u"Kiểu so sánh:")))
        section_control_row.Items.Add(forms.StackLayoutItem(self.section_comparison_mode))

        section_button_row = forms.StackLayout()
        section_button_row.Orientation = forms.Orientation.Horizontal
        section_button_row.Spacing = 8
        section_button_row.Items.Add(forms.StackLayoutItem(overlay_button))
        section_button_row.Items.Add(forms.StackLayoutItem(clear_overlay_button))

        heatmap_control_row = forms.StackLayout()
        heatmap_control_row.Orientation = forms.Orientation.Horizontal
        heatmap_control_row.Spacing = 8
        heatmap_control_row.Items.Add(forms.StackLayoutItem(forms.Label(Text=u"Đại lượng:")))
        heatmap_control_row.Items.Add(forms.StackLayoutItem(self.survey_heatmap_metric))
        heatmap_control_row.Items.Add(forms.StackLayoutItem(heatmap_button))

        heatmap_export_row = forms.StackLayout()
        heatmap_export_row.Orientation = forms.Orientation.Horizontal
        heatmap_export_row.Spacing = 8
        heatmap_export_row.Items.Add(forms.StackLayoutItem(heatmap_png_button))
        heatmap_export_row.Items.Add(forms.StackLayoutItem(heatmap_excel_button))

        survey_hydro_button_row = forms.StackLayout()
        survey_hydro_button_row.Orientation = forms.Orientation.Horizontal
        survey_hydro_button_row.Spacing = 8
        survey_hydro_button_row.Items.Add(forms.StackLayoutItem(calculate_survey_hydro_button))
        survey_hydro_button_row.Items.Add(forms.StackLayoutItem(cancel_survey_hydro_button))
        survey_hydro_button_row.Items.Add(forms.StackLayoutItem(export_survey_hydro_button))

        layout.AddRow(heading)
        layout.AddRow(None)
        layout.AddRow(
            forms.Label(Text=u"THAM SỐ NỀN")
        )
        layout.AddRow(self.survey_base_summary)
        layout.AddRow(None)
        layout.AddRow(count_row)
        layout.AddRow(
            forms.Label(Text=u"Góc vát đáy β - tối đa 10 giá trị (các cột của ma trận):")
        )
        layout.AddRow(beta_row)
        layout.AddRow(
            forms.Label(Text=u"Góc nghiêng sống mũi α - tối đa 10 giá trị (các hàng của ma trận):")
        )
        layout.AddRow(alpha_row)
        layout.AddRow(None)
        layout.AddRow(self.survey_matrix_summary)
        layout.AddRow(
            forms.Label(
                Text=u"MA TRẬN KHẢO SÁT"
            )
        )
        layout.Add(
            self.survey_matrix_preview,
            yscale=True
        )
        layout.AddRow(survey_model_button_row)
        layout.AddRow(None)
        layout.AddRow(forms.Label(Text=u"PHÂN TÍCH BIẾN DẠNG HÌNH HỌC SO VỚI MẪU NỀN"))
        layout.Add(self.survey_geometry_report_area, yscale=True)
        layout.AddRow(geometry_export_row)
        layout.AddRow(forms.Label(Text=u"SO SÁNH TIẾT DIỆN HÌNH HỌC"))
        layout.AddRow(section_control_row)
        layout.AddRow(section_button_row)
        layout.AddRow(self.section_overlay_report)
        layout.AddRow(None)
        layout.AddRow(
            forms.Label(
                Text=u"THỦY TĨNH CHO MA TRẬN KHẢO SÁT - MỘT MỚN NƯỚC CHUNG"
            )
        )
        layout.AddRow(
            self.survey_hydro_use_design_draft
        )
        layout.AddRow(
            survey_hydro_input_row
        )
        layout.AddRow(survey_hydro_button_row)
        layout.AddRow(
            self.survey_hydro_summary
        )
        layout.Add(
            self.survey_hydro_report_area,
            yscale=True
        )
        layout.AddRow(None)
        layout.AddRow(forms.Label(Text=u"MA TRẬN / HEATMAP KẾT QUẢ"))
        layout.AddRow(heatmap_control_row)
        layout.AddRow(heatmap_export_row)
        layout.Add(self.survey_heatmap_area)
        layout.AddRow(None)

        layout.Add(
            build_guidance_panel(
                u"HƯỚNG DẪN KHẢO SÁT MẪU",
                SURVEY_GUIDANCE_TEXT,
                270
            )
        )
        layout.AddRow(None)

        self.survey_beta_count.ValueChanged += self.on_survey_count_changed
        self.survey_alpha_count.ValueChanged += self.on_survey_count_changed

        self.update_survey_controls_state()
        self.update_survey_base_summary()
        self.update_survey_summary()

        scroll = forms.Scrollable()
        scroll.Content = layout

        container = forms.DynamicLayout()
        container.Add(scroll, yscale=True)
        return container


    def build_hydrostatic_mode(self):
        # ---------------------------------------------------------------------
        # CHẾ ĐỘ 3 - TÍNH TOÁN THỦY TĨNH
        # ---------------------------------------------------------------------
        # Toàn bộ hình dáng L, B, H, chine, sheer, vách đuôi, beta, alpha...
        # được lấy từ self.params của Chế độ 1 ngay khi nhấn nút Tính.
        # Mớn nước có thể dùng T thiết kế hoặc nhập một giá trị riêng.
        # ---------------------------------------------------------------------
        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(12)
        layout.Spacing = drawing.Size(8, 8)

        heading = forms.Label(Text=u"CHẾ ĐỘ 3 - TÍNH TOÁN THỦY TĨNH")
        heading.Font = drawing.Font(
            heading.Font.Family,
            12,
            drawing.FontStyle.Bold
        )

        self.hydro_base_summary = forms.Label(Text=u"")
        self.hydro_base_summary.Wrap = forms.WrapMode.Word

        self.hydro_use_design_draft = forms.CheckBox(
            Text=u"Dùng chiều chìm T hiện tại của Chế độ 1"
        )
        self.hydro_use_design_draft.Checked = True
        self.hydro_use_design_draft.CheckedChanged += self.on_hydro_draft_mode_changed

        self.hydro_draft_input = forms.NumericStepper()
        self.hydro_draft_input.Width = 110
        self.hydro_draft_input.MinValue = 0.0
        self.hydro_draft_input.MaxValue = max(
            0.10,
            float(self.params.depth / self.params.units_per_meter) - 0.01
        )
        self.hydro_draft_input.Increment = 0.05
        self.hydro_draft_input.DecimalPlaces = 3
        self.hydro_draft_input.Value = (
            self.params.draft / self.params.units_per_meter
        )
        self.hydro_draft_input.Enabled = False

        self.hydro_density_input = forms.NumericStepper()
        self.hydro_density_input.Width = 110
        self.hydro_density_input.MinValue = 0.50
        self.hydro_density_input.MaxValue = 1.50
        self.hydro_density_input.Increment = 0.001
        self.hydro_density_input.DecimalPlaces = 4
        self.hydro_density_input.Value = 1.025

        single_row = forms.DynamicLayout()
        single_row.Spacing = drawing.Size(8, 0)
        single_row.AddRow(
            forms.Label(Text=u"Mớn nước tính toán:"),
            self.hydro_draft_input,
            forms.Label(Text=u"m"),
            forms.Label(Text=u"Khối lượng riêng ρ:"),
            self.hydro_density_input,
            forms.Label(Text=u"t/m³"),
            None
        )

        calc_single_button = forms.Button(Text=u"Tính 1 mớn nước")
        calc_single_button.Width = 150
        calc_single_button.Click += self.on_calculate_hydro_single

        self.hydro_result_label = forms.Label(Text=u"Chưa có kết quả.")
        self.hydro_result_label.Wrap = forms.WrapMode.Word
        model112_set_table_font(self.hydro_result_label)

               
        # Báo cáo lớn luôn hiển thị toàn bộ bảng một mớn hoặc dải mớn.
        self.hydro_report_area = forms.TextArea()
        self.hydro_report_area.ReadOnly = True
        self.hydro_report_area.Wrap = False
        model112_set_table_font(self.hydro_report_area)
        self.hydro_report_area.Height = 330
        self.hydro_report_area.Text = u"Chưa có dữ liệu."

        # --- Nhiều mớn nước ---------------------------------------------------
        # T_i = T0 + i * Spacing, i = 0..N-1.
        # Mặc định 7 mức và cho phép bắt đầu từ 0.000 m.
        self.hydro_range_start = forms.NumericStepper()
        self.hydro_range_start.Width = 90
        self.hydro_range_start.MinValue = 0.0
        self.hydro_range_start.MaxValue = 20.0
        self.hydro_range_start.Increment = 0.05
        self.hydro_range_start.DecimalPlaces = 3
        self.hydro_range_start.Value = 0.0

        self.hydro_range_count = forms.NumericStepper()
        self.hydro_range_count.Width = 80
        self.hydro_range_count.MinValue = 1
        self.hydro_range_count.MaxValue = 100
        self.hydro_range_count.Increment = 1
        self.hydro_range_count.DecimalPlaces = 0
        self.hydro_range_count.Value = 7

        self.hydro_range_step = forms.NumericStepper()
        self.hydro_range_step.Width = 90
        self.hydro_range_step.MinValue = 0.001
        self.hydro_range_step.MaxValue = 2.00
        self.hydro_range_step.Increment = 0.05
        self.hydro_range_step.DecimalPlaces = 3
        self.hydro_range_step.Value = 0.50

        self.hydro_range_end_preview = forms.Label(
            Text=u"T cuối = 3.000 m"
        )

        self.hydro_range_start.ValueChanged += (
            self.on_hydro_range_spacing_changed
        )
        self.hydro_range_count.ValueChanged += (
            self.on_hydro_range_spacing_changed
        )
        self.hydro_range_step.ValueChanged += (
            self.on_hydro_range_spacing_changed
        )

        range_row = forms.DynamicLayout()
        range_row.Spacing = drawing.Size(8, 0)
        range_row.AddRow(
            forms.Label(Text=u"T bắt đầu:"),
            self.hydro_range_start,
            forms.Label(Text=u"m"),
            forms.Label(Text=u"Số đường nước:"),
            self.hydro_range_count,
            forms.Label(Text=u"Spacing ΔT:"),
            self.hydro_range_step,
            forms.Label(Text=u"m"),
            self.hydro_range_end_preview,
            None
        )

        calc_range_button = forms.Button(Text=u"Tính nhiều mớn nước")
        calc_range_button.Width = 160
        calc_range_button.Click += self.on_calculate_hydro_range

        export_button = forms.Button(Text=u"Xuất bảng Excel...")
        export_button.Width = 150
        export_button.Click += self.on_export_hydro_xlsx

        hydro_single_button_row = forms.StackLayout()
        hydro_single_button_row.Orientation = forms.Orientation.Horizontal
        hydro_single_button_row.Spacing = 8
        hydro_single_button_row.Items.Add(forms.StackLayoutItem(calc_single_button))

        hydro_range_button_row = forms.StackLayout()
        hydro_range_button_row.Orientation = forms.Orientation.Horizontal
        hydro_range_button_row.Spacing = 8
        hydro_range_button_row.Items.Add(forms.StackLayoutItem(calc_range_button))
        hydro_range_button_row.Items.Add(forms.StackLayoutItem(export_button))

        self.hydro_range_summary = forms.Label(
            Text=u"Chưa tính bảng thủy tĩnh."
        )
        self.hydro_range_summary.Wrap = forms.WrapMode.Word

                
        # Lưu riêng kết quả đơn và kết quả dải để không ghi đè lẫn nhau.
        self.hydro_single_results = []
        self.hydro_range_results = []
        self.last_hydro_results = []
        self.last_hydro_result_kind = None
        self.last_hydro_signature = None
        self.hydro_quality_label = forms.Label(Text=u"Chưa kiểm tra chất lượng kết quả.")
        self.hydro_quality_label.Wrap = forms.WrapMode.Word

        layout.AddRow(heading)
        layout.AddRow(None)
        layout.AddRow(forms.Label(Text=u"THÔNG SỐ HÌNH DÁNG KẾ THỪA TỪ CHẾ ĐỘ 1"))
        layout.AddRow(self.hydro_base_summary)
        layout.AddRow(None)
        layout.AddRow(forms.Label(Text=u"TÍNH TẠI MỘT MỚN NƯỚC"))
        layout.AddRow(self.hydro_use_design_draft)
        layout.AddRow(single_row)
        layout.AddRow(hydro_single_button_row)
        layout.AddRow(self.hydro_result_label)
        layout.AddRow(None)
        layout.AddRow(forms.Label(Text=u"NHIỀU ĐƯỜNG NƯỚC - START + SỐ LƯỢNG + SPACING"))
        layout.AddRow(range_row)
        layout.AddRow(hydro_range_button_row)
        layout.AddRow(self.hydro_range_summary)
        layout.AddRow(None)
        layout.AddRow(
            forms.Label(
                Text=u"BẢNG KẾT QUẢ"
            )
        )
        layout.Add(
            self.hydro_report_area,
            yscale=True
        )
        layout.AddRow(None)

        layout.Add(
            build_guidance_panel(
                u"HƯỚNG DẪN ĐẠI LƯỢNG THỦY TĨNH",
                HYDRO_GUIDANCE_TEXT,
                310
            )
        )

        self.update_hydro_base_summary()
        self.on_hydro_range_spacing_changed(
            None,
            None
        )

        scroll = forms.Scrollable()
        scroll.Content = layout

        container = forms.DynamicLayout()
        container.Add(scroll, yscale=True)
        return container



    def build_linesplan_mode(self):
        # ---------------------------------------------------------------------
        # CHẾ ĐỘ 2 - TẠO ĐƯỜNG HÌNH 2D
        # ---------------------------------------------------------------------
        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(12)
        layout.Spacing = drawing.Size(8, 8)

        heading = forms.Label(
            Text=u"CHẾ ĐỘ 2 - TẠO ĐƯỜNG HÌNH 2D TỰ ĐỘNG"
        )
        heading.Font = drawing.Font(
            heading.Font.Family,
            12,
            drawing.FontStyle.Bold
        )

        self.linesplan_base_summary = forms.Label(
            Text=u""
        )
        self.linesplan_base_summary.Wrap = (
            forms.WrapMode.Word
        )

        self.linesplan_station_count = (
            forms.NumericStepper()
        )
        self.linesplan_station_count.Width = 90
        self.linesplan_station_count.MinValue = 3
        self.linesplan_station_count.MaxValue = 30
        self.linesplan_station_count.Increment = 1
        self.linesplan_station_count.DecimalPlaces = 0
        self.linesplan_station_count.Value = 11

        self.linesplan_waterline_count = (
            forms.NumericStepper()
        )
        self.linesplan_waterline_count.Width = 90
        self.linesplan_waterline_count.MinValue = 1
        self.linesplan_waterline_count.MaxValue = 30
        self.linesplan_waterline_count.Increment = 1
        self.linesplan_waterline_count.DecimalPlaces = 0
        self.linesplan_waterline_count.Value = 7

        self.linesplan_buttock_count = (
            forms.NumericStepper()
        )
        self.linesplan_buttock_count.Width = 90
        self.linesplan_buttock_count.MinValue = 1
        self.linesplan_buttock_count.MaxValue = 20
        self.linesplan_buttock_count.Increment = 1
        self.linesplan_buttock_count.DecimalPlaces = 0
        self.linesplan_buttock_count.Value = 5

        self.linesplan_individual_layer_check = (
            forms.CheckBox(
                Text=u"Nguồn 3D gom theo Station / Waterline / Buttock / HullLine"
            )
        )
        self.linesplan_individual_layer_check.Checked = False
        self.linesplan_individual_layer_check.Enabled = False

        # -------------------------------------------------------------
        # SPACING - KIỂM SOÁT VỊ TRÍ CÁC ĐƯỜNG HÌNH
        # -------------------------------------------------------------
        self.linesplan_custom_spacing_check = (
            forms.CheckBox(
                Text=u"Dùng Spacing tùy chỉnh vị trí"
            )
        )
        self.linesplan_custom_spacing_check.Checked = False
        self.linesplan_custom_spacing_check.CheckedChanged += (
            self.on_linesplan_spacing_mode_changed
        )

        self.linesplan_station_start = forms.NumericStepper()
        self.linesplan_station_start.Width = 90
        self.linesplan_station_start.MinValue = 0.0
        self.linesplan_station_start.MaxValue = 1000.0
        self.linesplan_station_start.Increment = 0.10
        self.linesplan_station_start.DecimalPlaces = 3
        self.linesplan_station_start.Value = 0.0

        self.linesplan_station_spacing = forms.NumericStepper()
        self.linesplan_station_spacing.Width = 90
        self.linesplan_station_spacing.MinValue = 0.001
        self.linesplan_station_spacing.MaxValue = 1000.0
        self.linesplan_station_spacing.Increment = 0.10
        self.linesplan_station_spacing.DecimalPlaces = 3
        self.linesplan_station_spacing.Value = 2.4

        self.linesplan_waterline_start = forms.NumericStepper()
        self.linesplan_waterline_start.Width = 90
        self.linesplan_waterline_start.MinValue = 0.0
        self.linesplan_waterline_start.MaxValue = 1000.0
        self.linesplan_waterline_start.Increment = 0.10
        self.linesplan_waterline_start.DecimalPlaces = 3
        self.linesplan_waterline_start.Value = 0.0

        self.linesplan_waterline_spacing = forms.NumericStepper()
        self.linesplan_waterline_spacing.Width = 90
        self.linesplan_waterline_spacing.MinValue = 0.001
        self.linesplan_waterline_spacing.MaxValue = 1000.0
        self.linesplan_waterline_spacing.Increment = 0.10
        self.linesplan_waterline_spacing.DecimalPlaces = 3
        self.linesplan_waterline_spacing.Value = 0.5

        self.linesplan_buttock_start = forms.NumericStepper()
        self.linesplan_buttock_start.Width = 90
        self.linesplan_buttock_start.MinValue = 0.0
        self.linesplan_buttock_start.MaxValue = 1000.0
        self.linesplan_buttock_start.Increment = 0.10
        self.linesplan_buttock_start.DecimalPlaces = 3
        self.linesplan_buttock_start.Value = 0.0

        self.linesplan_buttock_spacing = forms.NumericStepper()
        self.linesplan_buttock_spacing.Width = 90
        self.linesplan_buttock_spacing.MinValue = 0.001
        self.linesplan_buttock_spacing.MaxValue = 1000.0
        self.linesplan_buttock_spacing.Increment = 0.10
        self.linesplan_buttock_spacing.DecimalPlaces = 3
        self.linesplan_buttock_spacing.Value = 0.5

        self.linesplan_auto_spacing_button = forms.Button(
            Text=u"Tính spacing đều theo kích thước"
        )
        self.linesplan_auto_spacing_button.Click += (
            self.on_linesplan_auto_spacing
        )

        count_row = forms.DynamicLayout()
        count_row.Spacing = drawing.Size(10, 0)
        count_row.AddRow(
            forms.Label(
                Text=u"Số sườn:"
            ),
            self.linesplan_station_count,
            forms.Label(
                Text=u"Số đường nước:"
            ),
            self.linesplan_waterline_count,
            forms.Label(
                Text=u"Số CD:"
            ),
            self.linesplan_buttock_count,
            None
        )

        station_spacing_row = forms.DynamicLayout()
        station_spacing_row.Spacing = drawing.Size(8, 0)
        station_spacing_row.AddRow(
            forms.Label(Text=u"Sườn: X bắt đầu"),
            self.linesplan_station_start,
            forms.Label(Text=u"m     ΔX"),
            self.linesplan_station_spacing,
            forms.Label(Text=u"m"),
            None
        )

        waterline_spacing_row = forms.DynamicLayout()
        waterline_spacing_row.Spacing = drawing.Size(8, 0)
        waterline_spacing_row.AddRow(
            forms.Label(Text=u"Đường nước: Z bắt đầu"),
            self.linesplan_waterline_start,
            forms.Label(Text=u"m     ΔZ"),
            self.linesplan_waterline_spacing,
            forms.Label(Text=u"m"),
            None
        )

        buttock_spacing_row = forms.DynamicLayout()
        buttock_spacing_row.Spacing = drawing.Size(8, 0)
        buttock_spacing_row.AddRow(
            forms.Label(Text=u"CD: Y bắt đầu"),
            self.linesplan_buttock_start,
            forms.Label(Text=u"m     ΔY"),
            self.linesplan_buttock_spacing,
            forms.Label(Text=u"m"),
            None
        )

        self.linesplan_status = forms.Label(
            Text=(
                u"Chưa tạo đường cắt 3D."
            )
        )
        self.linesplan_status.Wrap = (
            forms.WrapMode.Word
        )

        create_3d_button = forms.Button(
            Text=u"Tạo đường cắt 3D"
        )
        create_3d_button.Click += (
            self.on_create_linesplan_source
        )

        make2d_button = forms.Button(Text=u"Make2D - 1 bộ 3 hình")
        make2d_button.Click += self.on_make_linesplan_2d

        export_2d_button = forms.Button(Text=u"2D export")
        export_2d_button.Click += self.on_make_linesplan_export

        create_all_button = forms.Button(
            Text=u"Tạo tất cả"
        )
        create_all_button.Click += (
            self.on_create_linesplan_all
        )

        clear_button = forms.Button(
            Text=u"Xóa đường hình"
        )
        clear_button.Click += (
            self.on_clear_linesplan
        )

        button_row = forms.DynamicLayout()
        button_row.Spacing = drawing.Size(8, 0)
        button_row.AddRow(
            create_3d_button,
            make2d_button,
            export_2d_button,
            create_all_button,
            clear_button,
            None
        )

        # -------------------------------------------------------------
        # MODEL 112 V19 - BẢNG TỌA ĐỘ
        # -------------------------------------------------------------
        self.coordinate_unit_dropdown = forms.DropDown()
        self.coordinate_unit_dropdown.Width = 90
        self.coordinate_unit_dropdown.DataStore = list(
            self.coordinate_unit_options
        )
        self.coordinate_unit_dropdown.SelectedIndex = 0
        self.coordinate_unit_dropdown.SelectedIndexChanged += (
            self.on_coordinate_options_changed
        )

        self.coordinate_feature_dropdown = forms.DropDown()
        self.coordinate_feature_dropdown.Width = 220

        self.coordinate_axis_dropdown = forms.DropDown()
        self.coordinate_axis_dropdown.Width = 170
        self.coordinate_axis_dropdown.DataStore = list(
            self.coordinate_axis_options
        )
        self.coordinate_axis_dropdown.SelectedIndex = 0

        self.coordinate_column_name = forms.TextBox()
        self.coordinate_column_name.Width = 120
        self.coordinate_column_name.Text = u"MẠN"

        add_coordinate_column_button = forms.Button(
            Text=u"+ Thêm cột"
        )
        add_coordinate_column_button.Click += (
            self.on_add_coordinate_column
        )

        remove_coordinate_column_button = forms.Button(
            Text=u"Xóa cột cuối"
        )
        remove_coordinate_column_button.Click += (
            self.on_remove_coordinate_column
        )

        coordinate_option_row = forms.DynamicLayout()
        coordinate_option_row.Spacing = drawing.Size(8, 0)
        coordinate_option_row.AddRow(
            forms.Label(Text=u"Đơn vị:"),
            self.coordinate_unit_dropdown,
            forms.Label(Text=u"Đường bổ sung:"),
            self.coordinate_feature_dropdown,
            forms.Label(Text=u"Lấy:"),
            self.coordinate_axis_dropdown,
            forms.Label(Text=u"Tên cột:"),
            self.coordinate_column_name,
            add_coordinate_column_button,
            remove_coordinate_column_button,
            None
        )

        self.coordinate_extra_summary = forms.TextArea()
        self.coordinate_extra_summary.ReadOnly = True
        self.coordinate_extra_summary.Wrap = False
        model112_set_table_font(self.coordinate_extra_summary)
        self.coordinate_extra_summary.Height = 58
        self.coordinate_extra_summary.Text = (
            u"Chưa có cột bổ sung."
        )

        create_coordinate_button = forms.Button(
            Text=u"Tạo bảng tọa độ"
        )
        create_coordinate_button.Click += (
            self.on_create_coordinate_table
        )

        export_coordinate_button = forms.Button(
            Text=u"Xuất Excel (.xlsx)"
        )
        export_coordinate_button.Click += (
            self.on_export_coordinate_xlsx
        )

        coordinate_button_row = forms.DynamicLayout()
        coordinate_button_row.Spacing = drawing.Size(8, 0)
        coordinate_button_row.AddRow(
            create_coordinate_button,
            export_coordinate_button,
            None
        )

        self.coordinate_table_summary = forms.Label(
            Text=u"Chưa tạo bảng tọa độ."
        )
        self.coordinate_table_summary.Wrap = forms.WrapMode.Word

        self.coordinate_table_preview = forms.TextArea()
        self.coordinate_table_preview.ReadOnly = True
        self.coordinate_table_preview.Wrap = False
        model112_set_table_font(self.coordinate_table_preview)
        self.coordinate_table_preview.Height = 280
        self.coordinate_table_preview.Text = (
            u"Chưa có bảng tọa độ."
        )

        self.refresh_coordinate_feature_dropdown()
        self.update_coordinate_extra_summary()

        layout.AddRow(
            heading
        )
        layout.AddRow(
            None
        )
        layout.AddRow(
            forms.Label(
                Text=u"THÔNG SỐ HÌNH DÁNG KẾ THỪA TỪ TRANG 1"
            )
        )
        layout.AddRow(
            self.linesplan_base_summary
        )
        layout.AddRow(
            None
        )
        layout.AddRow(
            forms.Label(
                Text=u"MẬT ĐỘ ĐƯỜNG HÌNH"
            )
        )
        layout.AddRow(
            count_row
        )
        layout.AddRow(
            None
        )
        layout.AddRow(
            forms.Label(
                Text=u"SPACING – KIỂM SOÁT VỊ TRÍ"
            )
        )
        layout.AddRow(
            self.linesplan_custom_spacing_check,
            self.linesplan_auto_spacing_button,
            None
        )
        layout.AddRow(
            station_spacing_row
        )
        layout.AddRow(
            waterline_spacing_row
        )
        layout.AddRow(
            buttock_spacing_row
        )
        layout.AddRow(
            None
        )
        layout.AddRow(
            forms.Label(
                Text=u"TỔ CHỨC LAYER"
            )
        )
        layout.AddRow(
            self.linesplan_individual_layer_check
        )
        layout.AddRow(
            None
        )
        layout.AddRow(forms.Label(
            Text=u"Make2D: 3 hình chiếu 2D trực tiếp từ SOURCE_3D; "
                 u"2D export: Starboard, đuôi trái/mũi phải; mỗi lần chỉ giữ 1 bộ."
        ))
        layout.AddRow(None)
        layout.AddRow(
            button_row
        )
        layout.AddRow(
            self.linesplan_status
        )
        layout.AddRow(
            None
        )
        layout.AddRow(
            forms.Label(
                Text=u"BẢNG TỌA ĐỘ – GIAO ĐIỂM SƯỜN / ĐƯỜNG NƯỚC / CD"
            )
        )
        layout.AddRow(
            forms.Label(
                Text=(
                    u"Đo trực tiếp trên khung 3D: X = chiều dài; nửa rộng = |Y| từ Centerline; "
                    u"cao = Z - Baseline (được phép âm). Mỗi hàng là một sườn; ĐN lấy |Y| tại Sườn×WL, "
                    u"CD lấy cao độ tại Sườn×CD. Không dùng tọa độ bản vẽ Make2D."
                )
            )
        )
        layout.AddRow(
            coordinate_option_row
        )
        layout.Add(
            self.coordinate_extra_summary
        )
        layout.AddRow(
            coordinate_button_row
        )
        layout.AddRow(
            self.coordinate_table_summary
        )
        layout.Add(
            self.coordinate_table_preview,
            yscale=False
        )
        layout.AddRow(
            None
        )
        layout.Add(
            build_guidance_panel(
                u"HƯỚNG DẪN TẠO SƯỜN – ĐƯỜNG NƯỚC – CD – SPACING – MAKE2D",
                LINESPLAN_GUIDANCE_TEXT,
                390
            )
        )
        layout.AddRow(
            None
        )

        self.update_linesplan_base_summary()
        self.update_linesplan_spacing_defaults()
        self.on_linesplan_spacing_mode_changed(
            None,
            None
        )

        scroll = forms.Scrollable()
        scroll.Content = layout

        container = forms.DynamicLayout()
        container.Add(
            scroll,
            yscale=True
        )

        return container


    def update_linesplan_base_summary(self):
        if not hasattr(
            self,
            "linesplan_base_summary"
        ):
            return

        units = float(
            self.params.units_per_meter
        )

        half_text = (
            u"Nửa mạn Starboard"
            if bool(
                getattr(
                    self.params,
                    "create_half_model",
                    False
                )
            )
            else u"Đủ hai mạn"
        )

        self.linesplan_base_summary.Text = (
            u"Lmax = {0:.2f} m | Bmax = {1:.2f} m | H = {2:.2f} m | "
            u"T = {3:.2f} m | Bk = {4:.3f} m | β = {5:.2f}° | "
            u"α = {6:.2f}° | Số đường gãy = {7:d} | {8}.\n"
            u"Trang 2 cắt trực tiếp bề mặt dựng từ tham số hiện tại. "
            u"Khi bật nửa mạn, Station và Waterline chỉ giữ phần Y ≥ 0."
        ).format(
            self.params.length / units,
            self.params.beam / units,
            self.params.depth / units,
            self.params.draft / units,
            getattr(
                self.params,
                "keel_width",
                0.0
            ) / units,
            self.params.deadrise_midship_angle,
            self.params.bow_rake_angle,
            int(
                self.params.total_knuckle_count_per_side
            ),
            half_text
        )


    def update_linesplan_spacing_defaults(self):
        """
        Tính spacing đều sao cho các giá trị mặc định trùng với chế độ chia đều:

        Station:
            X0 = 0
            ΔX = Lmax / (Ns - 1)

        Waterline:
            Z0 = 0
            ΔZ = H / Nwl
            -> Nwl đường: 0, ΔZ, ..., (Nwl-1)·ΔZ; không ép đường cuối tại H.

        CD:
            Y0 = 0
            ΔY = (Bmax/2) / Ncd
            -> Ncd đường: 0, ΔY, ..., (Ncd-1)·ΔY; không ép đường cuối tại Bmax/2.
        """
        if not hasattr(
            self,
            "linesplan_station_spacing"
        ):
            return

        (
            station_count,
            waterline_count,
            buttock_count
        ) = self.get_linesplan_counts()

        units = float(
            self.params.units_per_meter
        )

        L_m = (
            float(
                self.params.length
            ) /
            units
        )
        B_m = (
            float(
                self.params.beam
            ) /
            units
        )
        H_m = (
            float(
                self.params.depth
            ) /
            units
        )

        self.linesplan_station_start.Value = 0.0

        if station_count > 1:
            self.linesplan_station_spacing.Value = (
                L_m /
                float(
                    station_count - 1
                )
            )

        if waterline_count > 0:
            # V19: Waterline 0 nằm đúng tại Baseline (Z - BaselineZ = 0).
            # Chia N đường từ 0 và để đường cuối thấp hơn H một bước,
            # tránh ép giao tuyến đúng mép trên có thể suy biến thành điểm.
            waterline_step = (
                H_m /
                float(
                    waterline_count
                )
            )
            self.linesplan_waterline_start.Value = 0.0
            self.linesplan_waterline_spacing.Value = (
                waterline_step
            )

        if buttock_count > 0:
            # V19: CD0 nằm trên mặt phẳng dọc tâm Y = 0.
            # Chia N đường từ Centerline và để đường cuối nhỏ hơn Bmax/2
            # một bước để tránh đường biên ngoài suy biến.
            buttock_step = (
                (B_m * 0.5) /
                float(
                    buttock_count
                )
            )
            self.linesplan_buttock_start.Value = 0.0
            self.linesplan_buttock_spacing.Value = (
                buttock_step
            )


    def on_linesplan_auto_spacing(
        self,
        sender,
        event
    ):
        self.update_linesplan_spacing_defaults()

        self.linesplan_status.Text = (
            u"Đã tính lại spacing: Sườn0 X=0, ĐN0 Z=0, CD0 Y=0; các đường tiếp theo chia đều theo Lmax, H và Bmax/2."
        )


    def on_linesplan_spacing_mode_changed(
        self,
        sender,
        event
    ):
        custom_enabled = bool(
            self.linesplan_custom_spacing_check.Checked
        )

        spacing_controls = [
            self.linesplan_station_start,
            self.linesplan_station_spacing,
            self.linesplan_waterline_start,
            self.linesplan_waterline_spacing,
            self.linesplan_buttock_start,
            self.linesplan_buttock_spacing
        ]

        for control in spacing_controls:
            control.Enabled = (
                custom_enabled
            )

        if hasattr(
            self,
            "linesplan_auto_spacing_button"
        ):
            self.linesplan_auto_spacing_button.Enabled = True


    def get_linesplan_custom_positions(self):
        """
        Trả ba danh sách vị trí theo model units.

        Nếu chưa bật custom spacing thì trả (None, None, None), để engine
        dùng logic chia đều mặc định.
        """
        if not bool(
            self.linesplan_custom_spacing_check.Checked
        ):
            return (
                None,
                None,
                None
            )

        (
            station_count,
            waterline_count,
            buttock_count
        ) = self.get_linesplan_counts()

        units = float(
            self.params.units_per_meter
        )

        L_local = float(
            self.params.length
        )
        B_local = float(
            self.params.beam
        )
        H_local = float(
            self.params.depth
        )
        z0 = float(
            self.params.baseline_z
        )

        station_start = model_units_from_meters(
            float(
                self.linesplan_station_start.Value
            ),
            units
        )
        station_spacing = model_units_from_meters(
            float(
                self.linesplan_station_spacing.Value
            ),
            units
        )

        waterline_start = (
            z0 +
            model_units_from_meters(
                float(
                    self.linesplan_waterline_start.Value
                ),
                units
            )
        )
        waterline_spacing = model_units_from_meters(
            float(
                self.linesplan_waterline_spacing.Value
            ),
            units
        )

        buttock_start = model_units_from_meters(
            float(
                self.linesplan_buttock_start.Value
            ),
            units
        )
        buttock_spacing = model_units_from_meters(
            float(
                self.linesplan_buttock_spacing.Value
            ),
            units
        )

        station_values = custom_spaced_values(
            station_start,
            station_spacing,
            station_count,
            0.0,
            L_local,
            u"sườn X"
        )

        waterline_values = custom_spaced_values(
            waterline_start,
            waterline_spacing,
            waterline_count,
            z0,
            z0 + H_local,
            u"đường nước Z"
        )

        buttock_values = custom_spaced_values(
            buttock_start,
            buttock_spacing,
            buttock_count,
            0.0,
            B_local * 0.5,
            u"CD Y"
        )

        return (
            station_values,
            waterline_values,
            buttock_values
        )



    def get_linesplan_counts(self):
        station_count = int(
            round(
                float(
                    self.linesplan_station_count.Value
                )
            )
        )

        waterline_count = int(
            round(
                float(
                    self.linesplan_waterline_count.Value
                )
            )
        )

        buttock_count = int(
            round(
                float(
                    self.linesplan_buttock_count.Value
                )
            )
        )

        return (
            station_count,
            waterline_count,
            buttock_count
        )


    def on_create_linesplan_source(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        self.update_linesplan_base_summary()

        (
            station_count,
            waterline_count,
            buttock_count
        ) = self.get_linesplan_counts()

        self.status_label.Text = (
            u"Đang tạo sườn, đường nước và CD..."
        )

        before_ids = all_document_object_ids()

        try:
            (
                station_positions,
                waterline_positions,
                buttock_positions
            ) = self.get_linesplan_custom_positions()

            result = (
                create_linesplan_source_curves(
                    copy.deepcopy(
                        self.params
                    ),
                    station_count,
                    waterline_count,
                    buttock_count,
                    False,
                    station_positions,
                    waterline_positions,
                    buttock_positions
                )
            )

            self.linesplan_status.Text = (
                u"Đã tạo nguồn 3D: %d curve sườn | %d curve đường nước | "
                u"%d curve CD | %d curve Keel/Chine/Sheer. "
                u"Nguồn được gom vào 4 layer cố định Station / Waterline / Buttock / HullLine. Chế độ vị trí: %s."
            ) % (
                len(
                    result["station_ids"]
                ),
                len(
                    result["waterline_ids"]
                ),
                len(
                    result["buttock_ids"]
                ),
                len(
                    result.get(
                        "hull_line_ids",
                        []
                    )
                ),
                (
                    u"Spacing tùy chỉnh"
                    if bool(
                        self.linesplan_custom_spacing_check.Checked
                    )
                    else
                    u"Chia đều tự động"
                )
            )

            self.status_label.Text = (
                u"Đã tạo đường cắt 3D"
            )

        except Exception as error:
            delete_document_objects_created_since(
                before_ids
            )
            self.linesplan_status.Text = (
                u"Tạo đường cắt 3D thất bại: %s" %
                str(
                    error
                )
            )

            self.status_label.Text = (
                u"Tạo đường cắt 3D thất bại"
            )

            Rhino.RhinoApp.WriteLine(
                "Model 112 lines plan source error: %s" %
                str(
                    error
                )
            )


    def on_make_linesplan_2d(self, sender, event):
        self._make_linesplan_2d(sender, event, False)

    def on_make_linesplan_export(self, sender, event):
        self._make_linesplan_2d(sender, event, True)

    def _make_linesplan_2d(self, sender, event, export_drawing):
        self.preview_timer.Stop()

        source_data = sc.sticky.get(
            LINESPLAN_DATA_STICKY_KEY,
            {}
        )

        if not source_data:
            forms.MessageBox.Show(
                u"Chưa có đường cắt 3D. Hãy bấm 'Tạo đường cắt 3D' trước.",
                u"Đường hình 2D"
            )
            return

        source_signature = source_data.get("parameter_signature")
        if source_signature != build_hull_parameter_signature(self.params):
            forms.MessageBox.Show(
                u"Nguồn 3D được tạo từ tham số cũ. Hãy bấm 'Tạo đường cắt 3D' "
                u"rồi mới tạo lại bản vẽ 2D.",
                u"Đường hình 2D"
            )
            return

        self.status_label.Text = (
            u"Đang chiếu ba hình 2D trực tiếp..."
        )

        before_ids = all_document_object_ids()
        source_states = linesplan_source_layer_visibility()

        drawing_was_visible = (bool(rs.IsLayerVisible(LINESPLAN_2D_OUTPUT_LAYER))
                               if rs.IsLayer(LINESPLAN_2D_OUTPUT_LAYER)
                               else False)
        export_was_visible = (bool(rs.IsLayerVisible(LINESPLAN_EXPORT_OUTPUT_LAYER))
                              if rs.IsLayer(LINESPLAN_EXPORT_OUTPUT_LAYER)
                              else False)
        hidden_source_ids = []

        try:
            # RC14 uses RhinoCommon geometry directly, including hidden layers:
            # do not show/move the source objects while generating drawings.
            hidden_source_ids = [object_id for object_id in
                                 model112_linesplan_source_object_ids()
                                 if rs.IsObject(object_id) and
                                 rs.IsObjectHidden(object_id)]
            result = create_linesplan_make2d(
                copy.deepcopy(
                    self.params
                ),
                source_data,
                False,
                export_drawing=export_drawing
            )

            drawing_kind = (u"2D EXPORT (nửa rộng; đuôi trái/mũi phải)"
                            if export_drawing else
                            u"MAKE2D ĐẦY ĐỦ (đủ hai mạn, tất cả sườn)")
            ensure_nested_layer(LINESPLAN_2D_OUTPUT_LAYER)
            ensure_nested_layer(LINESPLAN_EXPORT_OUTPUT_LAYER)
            rs.LayerVisible(LINESPLAN_2D_OUTPUT_LAYER, not export_drawing)
            rs.LayerVisible(LINESPLAN_EXPORT_OUTPUT_LAYER, export_drawing)
            if hidden_source_ids:
                rs.HideObjects(hidden_source_ids)
            if TEXT_TYPE(rs.CurrentLayer()).startswith(LINESPLAN_SOURCE_ROOT):
                ensure_nested_layer(LAYER_KHUNG)
                rs.CurrentLayer(LAYER_KHUNG)
            rs.LayerVisible(LINESPLAN_SOURCE_ROOT, False)
            hide_rhino_make2d_legacy_layers()
            rs.ZoomExtents()

            self.linesplan_status.Text = (
                u"%s: Hình đứng %d curve | Hình bằng %d curve | "
                u"Hình cạnh %d curve. Kết quả nằm trong %s; "
                u"SOURCE_3D được giữ lại và ẩn. RC14: FULL hai mạn, EXPORT nửa rộng/đuôi-mũi."
            ) % (
                drawing_kind,
                len(
                    result["profile_ids"]
                ),
                len(
                    result["plan_ids"]
                ),
                len(
                    result["body_ids"]
                ),
                result["output_layer"]
            )

            self.status_label.Text = (
                u"Đã tạo bản vẽ đường hình 2D"
            )

        except Exception as error:
            if hidden_source_ids:
                rs.HideObjects(hidden_source_ids)
            restore_linesplan_source_layer_visibility(source_states)
            if rs.IsLayer(LINESPLAN_2D_OUTPUT_LAYER):
                rs.LayerVisible(LINESPLAN_2D_OUTPUT_LAYER, drawing_was_visible)
            if rs.IsLayer(LINESPLAN_EXPORT_OUTPUT_LAYER):
                rs.LayerVisible(LINESPLAN_EXPORT_OUTPUT_LAYER, export_was_visible)
            delete_document_objects_created_since(
                before_ids
            )
            self.linesplan_status.Text = (
                u"Make2D tự động thất bại: %s\n"
                u"Kiểm tra nguồn 3D, chế độ bản xuất và Command History (F2)."
            ) % (
                str(
                    error
                )
            )

            self.status_label.Text = (
                u"Make2D tự động thất bại"
            )

            Rhino.RhinoApp.WriteLine(
                "Model 112 Make2D error: %s" %
                str(
                    error
                )
            )


    def on_create_linesplan_all(
        self,
        sender,
        event
    ):
        self.on_create_linesplan_source(
            sender,
            event
        )

        source_ids = list(
            sc.sticky.get(
                LINESPLAN_SOURCE_STICKY_KEY,
                []
            )
        )

        if source_ids:
            self.on_make_linesplan_2d(
                sender,
                event
            )


    def on_clear_linesplan(
        self,
        sender,
        event
    ):
        clear_sticky_objects(
            LINESPLAN_SOURCE_STICKY_KEY
        )
        clear_linesplan_2d_variant(LINESPLAN_2D_OUTPUT_LAYER,
                                    LINESPLAN_2D_STICKY_KEY)
        clear_linesplan_2d_variant(LINESPLAN_EXPORT_OUTPUT_LAYER,
                                    LINESPLAN_EXPORT_STICKY_KEY)
        rs.LayerVisible(LINESPLAN_SOURCE_ROOT, True)
        sc.sticky[
            LINESPLAN_DATA_STICKY_KEY
        ] = {}

        self.coordinate_table_data = None

        if hasattr(
            self,
            "coordinate_table_preview"
        ):
            self.coordinate_table_preview.Text = (
                u"Chưa có bảng tọa độ."
            )

        if hasattr(
            self,
            "coordinate_table_summary"
        ):
            self.coordinate_table_summary.Text = (
                u"Chưa tạo bảng tọa độ."
            )

        sc.doc.Views.Redraw()

        if hasattr(
            self,
            "linesplan_status"
        ):
            self.linesplan_status.Text = (
                u"Đã xóa đường cắt 3D và bản vẽ 2D."
            )

        self.status_label.Text = (
            u"Đã xóa đường hình 2D"
        )



    def refresh_coordinate_feature_dropdown(self):
        if not hasattr(
            self,
            "coordinate_feature_dropdown"
        ):
            return

        labels = build_hull_feature_level_labels(
            int(
                self.params.total_knuckle_count_per_side
            )
        )

        # Bk=0 không có dải keel riêng trong hull_line_records.
        if float(
            getattr(
                self.params,
                "keel_width",
                0.0
            )
        ) <= max(
            1.0e-9,
            model_units_from_mm(
                0.01,
                self.params.units_per_meter
            )
        ):
            labels = [
                label
                for label in labels
                if label != "Keel"
            ]

        old_text = None

        try:
            old_index = int(
                self.coordinate_feature_dropdown.SelectedIndex
            )

            if (
                old_index >= 0 and
                old_index < len(
                    self.coordinate_feature_options
                )
            ):
                old_text = (
                    self.coordinate_feature_options[
                        old_index
                    ]
                )
        except Exception:
            old_text = None

        self.coordinate_feature_options = [
            TEXT_TYPE(label)
            for label in labels
        ]

        self.coordinate_feature_dropdown.DataStore = list(
            self.coordinate_feature_options
        )

        selected_index = 0

        if old_text in self.coordinate_feature_options:
            selected_index = (
                self.coordinate_feature_options.index(
                    old_text
                )
            )

        if self.coordinate_feature_options:
            self.coordinate_feature_dropdown.SelectedIndex = (
                selected_index
            )
        else:
            self.coordinate_feature_dropdown.SelectedIndex = -1


    def update_coordinate_extra_summary(self):
        if not hasattr(
            self,
            "coordinate_extra_summary"
        ):
            return

        if not self.coordinate_extra_columns:
            self.coordinate_extra_summary.Text = (
                u"Chưa có cột bổ sung. Bảng mặc định chỉ dùng ĐN và CD hiện tại."
            )
            return

        lines = []

        for index, item in enumerate(
            self.coordinate_extra_columns,
            1
        ):
            axis_text = (
                u"Nửa chiều rộng Y"
                if item.get(
                    "axis"
                ) == "Y"
                else u"Chiều cao Z"
            )

            lines.append(
                u"%d. %s | %s | %s" %
                (
                    index,
                    TEXT_TYPE(
                        item.get(
                            "name",
                            ""
                        )
                    ),
                    TEXT_TYPE(
                        item.get(
                            "feature_label",
                            ""
                        )
                    ),
                    axis_text
                )
            )

        self.coordinate_extra_summary.Text = (
            u"\n".join(
                lines
            )
        )


    def on_coordinate_options_changed(
        self,
        sender,
        event
    ):
        self.coordinate_table_data = None

        if hasattr(
            self,
            "coordinate_table_summary"
        ):
            self.coordinate_table_summary.Text = (
                u"Định dạng đã thay đổi; hãy tạo lại bảng tọa độ."
            )


    def on_add_coordinate_column(
        self,
        sender,
        event
    ):
        self.refresh_coordinate_feature_dropdown()

        feature_index = int(
            self.coordinate_feature_dropdown.SelectedIndex
        )

        axis_index = int(
            self.coordinate_axis_dropdown.SelectedIndex
        )

        if (
            feature_index < 0 or
            feature_index >= len(
                self.coordinate_feature_options
            )
        ):
            forms.MessageBox.Show(
                u"Không có đường Keel/Chine/Sheer hợp lệ để thêm.",
                u"Bảng tọa độ"
            )
            return

        if (
            axis_index < 0 or
            axis_index >= len(
                self.coordinate_axis_options
            )
        ):
            axis_index = 0

        feature_label = (
            self.coordinate_feature_options[
                feature_index
            ]
        )

        axis = (
            "Y"
            if axis_index == 0
            else "Z"
        )

        column_name = TEXT_TYPE(
            self.coordinate_column_name.Text
        ).strip()

        if not column_name:
            column_name = TEXT_TYPE(
                feature_label
            )

        existing_names = [
            TEXT_TYPE(
                item.get(
                    "name",
                    ""
                )
            ).lower()
            for item in self.coordinate_extra_columns
        ]

        if column_name.lower() in existing_names:
            forms.MessageBox.Show(
                u"Tên cột bổ sung đã tồn tại. Hãy đặt tên khác.",
                u"Bảng tọa độ"
            )
            return

        self.coordinate_extra_columns.append(
            {
                "name": column_name,
                "feature_label": TEXT_TYPE(
                    feature_label
                ),
                "axis": axis
            }
        )

        self.coordinate_table_data = None
        self.update_coordinate_extra_summary()

        self.coordinate_column_name.Text = (
            u"CỘT%d" %
            (
                len(
                    self.coordinate_extra_columns
                ) + 1
            )
        )


    def on_remove_coordinate_column(
        self,
        sender,
        event
    ):
        if self.coordinate_extra_columns:
            self.coordinate_extra_columns.pop()
            self.coordinate_table_data = None

        self.update_coordinate_extra_summary()


    def get_coordinate_output_unit(self):
        if not hasattr(
            self,
            "coordinate_unit_dropdown"
        ):
            return u"mm"

        index = int(
            self.coordinate_unit_dropdown.SelectedIndex
        )

        if (
            index < 0 or
            index >= len(
                self.coordinate_unit_options
            )
        ):
            return u"mm"

        return self.coordinate_unit_options[
            index
        ]


    def build_coordinate_table_from_current_ui(self):
        self.refresh_coordinate_feature_dropdown()

        (
            station_count,
            waterline_count,
            buttock_count
        ) = self.get_linesplan_counts()

        (
            station_positions,
            waterline_positions,
            buttock_positions
        ) = self.get_linesplan_custom_positions()

        source_data = create_linesplan_source_curves(
            copy.deepcopy(
                self.params
            ),
            station_count,
            waterline_count,
            buttock_count,
            False,
            station_positions,
            waterline_positions,
            buttock_positions
        )

        table_data = build_linesplan_coordinate_table(
            copy.deepcopy(
                self.params
            ),
            source_data,
            list(
                self.coordinate_extra_columns
            ),
            self.get_coordinate_output_unit()
        )

        self.coordinate_table_data = table_data
        return table_data


    def on_create_coordinate_table(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        self.update_linesplan_base_summary()

        before_ids = all_document_object_ids()

        self.status_label.Text = (
            u"Đang tạo bảng tọa độ..."
        )

        try:
            table_data = (
                self.build_coordinate_table_from_current_ui()
            )

            self.coordinate_table_preview.Text = (
                format_linesplan_coordinate_table(
                    table_data
                )
            )

            self.coordinate_table_summary.Text = (
                u"Đã tạo bảng từ KHUNG 3D: %d sườn | %d ĐN | %d CD | %d cột bổ sung | đơn vị %s. "
                u"X=chiều dài, nửa rộng=|Y| từ Centerline, cao=Z-Baseline (được phép âm). "
                u"Max nửa rộng đo %.3f / giới hạn Bmax/2 %.3f %s."
            ) % (
                int(
                    table_data.get(
                        "station_count",
                        0
                    )
                ),
                int(
                    table_data.get(
                        "waterline_count",
                        0
                    )
                ),
                int(
                    table_data.get(
                        "buttock_count",
                        0
                    )
                ),
                len(
                    table_data.get(
                        "extra_columns",
                        []
                    )
                ),
                TEXT_TYPE(
                    table_data.get(
                        "unit",
                        u"mm"
                    )
                ),
                float(
                    table_data.get(
                        "max_measured_half_breadth_output",
                        0.0
                    )
                ),
                float(
                    table_data.get(
                        "max_half_beam_output",
                        0.0
                    )
                ),
                TEXT_TYPE(
                    table_data.get(
                        "unit",
                        u"mm"
                    )
                )
            )

            self.linesplan_status.Text = (
                u"Nguồn 3D đã được làm mới; bảng đo trực tiếp X/Y/Z trên Station / Waterline / Buttock, độc lập với vị trí Make2D."
            )

            self.status_label.Text = (
                u"Đã tạo bảng tọa độ"
            )

        except Exception as error:
            delete_document_objects_created_since(
                before_ids
            )

            self.coordinate_table_data = None
            self.coordinate_table_preview.Text = (
                u"Tạo bảng tọa độ thất bại:\n%s" %
                TEXT_TYPE(error)
            )
            self.coordinate_table_summary.Text = (
                u"Tạo bảng tọa độ thất bại."
            )
            self.status_label.Text = (
                u"Tạo bảng tọa độ thất bại"
            )

            Rhino.RhinoApp.WriteLine(
                "Model 112 coordinate table error: %s" %
                str(error)
            )


    def on_export_coordinate_xlsx(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        before_ids = all_document_object_ids()

        try:
            # Luôn tính lại ngay trước khi xuất để file khớp đúng tham số,
            # số Station/WL/CD và danh sách cột bổ sung hiện tại.
            table_data = (
                self.build_coordinate_table_from_current_ui()
            )

            self.coordinate_table_preview.Text = (
                format_linesplan_coordinate_table(
                    table_data
                )
            )

            default_name = build_coordinate_xlsx_filename(
                table_data
            )

            default_path = os.path.join(
                get_data_output_directory(),
                default_name
            )

            output_path = rs.SaveFileName(
                u"Xuất bảng tọa độ Model 112",
                u"Excel Workbook (*.xlsx)|*.xlsx||",
                os.path.dirname(
                    default_path
                ),
                os.path.splitext(
                    default_name
                )[0],
                u"xlsx"
            )

            if not output_path:
                self.status_label.Text = (
                    u"Đã hủy xuất bảng tọa độ"
                )
                return

            if not TEXT_TYPE(
                output_path
            ).lower().endswith(
                u".xlsx"
            ):
                output_path += u".xlsx"

            actual_path = output_path

            if os.path.exists(
                actual_path
            ):
                actual_path = make_duplicate_safe_path(
                    actual_path
                )

            write_linesplan_coordinate_xlsx(
                actual_path,
                table_data
            )

            self.coordinate_table_data = table_data
            self.coordinate_table_summary.Text = (
                u"Đã xuất Excel: %s" %
                TEXT_TYPE(
                    actual_path
                )
            )
            self.status_label.Text = (
                u"Đã xuất bảng tọa độ Excel"
            )

            forms.MessageBox.Show(
                u"Đã xuất bảng tọa độ:\n%s" %
                TEXT_TYPE(
                    actual_path
                ),
                u"MODEL 112"
            )

        except Exception as error:
            delete_document_objects_created_since(
                before_ids
            )

            self.status_label.Text = (
                u"Xuất bảng tọa độ thất bại"
            )

            forms.MessageBox.Show(
                u"Không xuất được bảng tọa độ Excel:\n%s" %
                TEXT_TYPE(
                    error
                ),
                u"MODEL 112"
            )


    def update_hydro_base_summary(self):
        if not hasattr(self, "hydro_base_summary"):
            return

        units = float(self.params.units_per_meter)
        self.hydro_base_summary.Text = (
            u"Lmax = %.2f m | Bmax = %.2f m | H = %.2f m | T thiết kế = %.2f m | Bk = %.3f m | "
            u"β = %.2f° | α = %.2f° | Số đường gãy = %d | Góc nghiêng vách đuôi = %.2f°.\n"
            u"Mọi tham số hình học khác cũng lấy trực tiếp từ Chế độ 1 tại thời điểm tính."
        ) % (
            self.params.length / units,
            self.params.beam / units,
            self.params.depth / units,
            self.params.draft / units,
            getattr(
                self.params,
                "keel_width",
                0.0
            ) / units,
            self.params.deadrise_midship_angle,
            self.params.bow_rake_angle,
            int(self.params.total_knuckle_count_per_side),
            self.params.transom_rake_angle
        )

        if hasattr(self, "hydro_draft_input"):
            self.hydro_draft_input.MaxValue = max(
                0.10,
                self.params.depth / units - 0.01
            )

            if bool(self.hydro_use_design_draft.Checked):
                self.hydro_draft_input.Value = self.params.draft / units


    def on_hydro_draft_mode_changed(self, sender, event):
        use_design = bool(self.hydro_use_design_draft.Checked)
        self.hydro_draft_input.Enabled = not use_design

        if use_design:
            self.hydro_draft_input.Value = (
                self.params.draft / self.params.units_per_meter
            )


    def get_hydro_single_draft(self):
        if bool(self.hydro_use_design_draft.Checked):
            return float(
                self.params.draft / self.params.units_per_meter
            )

        return float(self.hydro_draft_input.Value)


    def hydro_progress(self, current, total, draft_m):
        self.status_label.Text = (
            u"Đang tính thủy tĩnh %d/%d tại T = %.3f m..." %
            (current, total, draft_m)
        )
        Rhino.RhinoApp.SetCommandPrompt(self.status_label.Text)


    def get_hydro_signature(self, draft_values):
        return (
            build_hull_parameter_signature(self.params),
            round(float(self.hydro_density_input.Value), 9),
            tuple(round(float(value), 6) for value in draft_values)
        )

    def hydro_results_are_current(self):
        if not self.last_hydro_results or self.last_hydro_signature is None:
            return False
        try:
            drafts = ([self.get_hydro_single_draft()] if self.last_hydro_result_kind == "single"
                      else self.build_hydro_draft_series())
            return self.last_hydro_signature == self.get_hydro_signature(drafts)
        except Exception:
            return False

    def show_hydro_quality(self, results):
        # Technical notes are kept in the export, outside the visible table.
        available = len([r for r in results if r.get("status") != "INVALID"])
        self.hydro_quality_label.Text = (
            u"Có số liệu: %d/%d mớn; chi tiết kiểm tra lưu trong file Excel." %
            (available, len(results))
        )


    def on_calculate_hydro_single(self, sender, event):
        self.preview_timer.Stop()
        self.update_hydro_base_summary()

        draft_m = self.get_hydro_single_draft()
        density = float(self.hydro_density_input.Value)

        self.last_hydro_results = []
        self.last_hydro_signature = None
        self.hydro_result_label.Text = u"Đang tính mớn nước..."
        self.hydro_report_area.Text = format_hydrostatic_report_table([])
        self.status_label.Text = u"Đang tính thủy tĩnh..."

        try:
            results = calculate_hydrostatic_series(
                copy.deepcopy(self.params),
                [draft_m],
                density,
                self.hydro_progress,
                continue_on_error=True
            )

            self.hydro_single_results = list(
                results
            )

            self.last_hydro_results = list(
                results
            )

            self.last_hydro_result_kind = (
                "single"
            )
            self.last_hydro_signature = self.get_hydro_signature([draft_m])
            self.show_hydro_quality(results)

            result = results[0]
            self.hydro_result_label.Text = format_hydrostatic_result(result)

            self.hydro_report_area.Text = (
                format_hydrostatic_report_table(
                    results
                )
            )

            self.hydro_range_summary.Text = (
                u"Đã xử lý T = %.3f m. Có thể xuất bảng Excel để xem chi tiết kiểm tra." %
                draft_m
            )
            self.status_label.Text = u"Đã tính xong thủy tĩnh"
        except Exception as error:
            self.hydro_quality_label.Text = u"KHÔNG HỢP LỆ: %s" % TEXT_TYPE(error)
            self.status_label.Text = u"Tính thủy tĩnh thất bại"
            Rhino.RhinoApp.WriteLine(
                "Model 112 hydrostatic error: %s" % str(error)
            )
            forms.MessageBox.Show(
                u"Không tính được thủy tĩnh:\n%s" % str(error),
                u"Lỗi thủy tĩnh"
            )


    def on_hydro_range_spacing_changed(
        self,
        sender,
        event
    ):
        if not hasattr(
            self,
            "hydro_range_end_preview"
        ):
            return

        try:
            start = float(
                self.hydro_range_start.Value
            )
            count = int(
                round(
                    float(
                        self.hydro_range_count.Value
                    )
                )
            )
            spacing = float(
                self.hydro_range_step.Value
            )
            end_value = (
                start +
                max(0, count - 1) *
                spacing
            )
            self.hydro_range_end_preview.Text = (
                u"T cuối = %.3f m" %
                end_value
            )
        except Exception:
            self.hydro_range_end_preview.Text = u"T cuối = --"


    def build_hydro_draft_series(self):
        start = float(
            self.hydro_range_start.Value
        )
        count = int(
            round(
                float(
                    self.hydro_range_count.Value
                )
            )
        )
        spacing = float(
            self.hydro_range_step.Value
        )
        max_draft = (
            float(
                self.params.depth /
                self.params.units_per_meter
            ) -
            0.01
        )

        if start < 0.0:
            raise Exception(
                u"Mớn nước bắt đầu không được âm."
            )
        if count < 1:
            raise Exception(
                u"Số mức mớn nước phải ít nhất là 1."
            )
        if spacing <= 0.0 and count > 1:
            raise Exception(
                u"Spacing ΔT phải lớn hơn 0 khi N > 1."
            )

        values = [
            round(
                start +
                float(index) *
                spacing,
                6
            )
            for index in range(count)
        ]

        end_value = values[-1]
        if end_value > max_draft:
            raise Exception(
                (
                    u"Mớn nước cuối %.3f m vượt miền tính; "
                    u"phải nhỏ hơn H = %.3f m."
                ) %
                (
                    end_value,
                    self.params.depth /
                    self.params.units_per_meter
                )
            )

        return values


    def on_calculate_hydro_range(self, sender, event):
        self.preview_timer.Stop()
        self.update_hydro_base_summary()

        try:
            draft_values = self.build_hydro_draft_series()
            density = float(self.hydro_density_input.Value)
            partial_results = []
            self.hydro_range_results = []
            self.last_hydro_results = []
            self.last_hydro_result_kind = "range"
            self.last_hydro_signature = self.get_hydro_signature(draft_values)
            self.hydro_report_area.Text = format_hydrostatic_report_table([])
            self.hydro_result_label.Text = u"Đang tính dãy mớn nước..."
            self.hydro_range_summary.Text = u"Đang dựng vỏ để tính thủy tĩnh..."

            def show_finished_row(row, current, total):
                partial_results.append(row)
                self.hydro_range_results = list(partial_results)
                self.last_hydro_results = list(partial_results)
                self.hydro_report_area.Text = format_hydrostatic_report_table(
                    partial_results
                )
                valid_rows = [r for r in partial_results
                              if r.get("status") != "INVALID"]
                if valid_rows:
                    self.hydro_result_label.Text = format_hydrostatic_result(
                        valid_rows[-1]
                    )
                self.hydro_range_summary.Text = (
                    u"Đã xử lý %d/%d mức | Có số liệu: %d. "
                    u"Dòng vừa xử lý: T = %.3f m." %
                    (current, total, len(valid_rows),
                     float(row["draft_m"]))
                )

            results = calculate_hydrostatic_series(
                copy.deepcopy(self.params),
                draft_values,
                density,
                self.hydro_progress,
                row_callback=show_finished_row,
                continue_on_error=True
            )
            self.hydro_range_results = list(results)
            self.last_hydro_results = list(results)
            self.hydro_report_area.Text = format_hydrostatic_report_table(
                results
            )
            self.show_hydro_quality(results)
            success_rows = [r for r in results
                            if r.get("status") != "INVALID"]
            if not success_rows:
                self.hydro_result_label.Text = (
                    u"Chưa có mức nào trả về số liệu; xem file Excel để kiểm tra."
                )
            self.hydro_range_summary.Text = (
                u"Đã xử lý %d mức từ %.3f m đến %.3f m: %d mức có số liệu. "
                u"Chi tiết kiểm tra nằm dưới bảng trong file Excel." %
                (len(results), draft_values[0], draft_values[-1],
                 len(success_rows))
            )
            self.status_label.Text = (
                u"Bảng thủy tĩnh: %d/%d mức tính được" %
                (len(success_rows), len(results))
            )
        except Exception as error:
            self.hydro_quality_label.Text = (
                u"KHÔNG THỂ HOÀN TẤT DÃY MỚN NƯỚC: %s" % TEXT_TYPE(error)
            )
            self.status_label.Text = u"Tính bảng thủy tĩnh bị gián đoạn"
            Rhino.RhinoApp.WriteLine(
                "Model 112 hydrostatic range error: %s" % str(error)
            )
            if self.last_hydro_results:
                self.hydro_report_area.Text = format_hydrostatic_report_table(
                    self.last_hydro_results
                )
                self.hydro_range_summary.Text = (
                    u"Giữ %d dòng đã xử lý; lỗi chung: %s" %
                    (len(self.last_hydro_results), TEXT_TYPE(error))
                )
            else:
                forms.MessageBox.Show(
                    u"Không thể dựng/tính thủy tĩnh:\\n%s" % TEXT_TYPE(error),
                    u"Lỗi thủy tĩnh"
                )


    def on_export_hydro_xlsx(self, sender, event):
        """
        - Mở Save As để người dùng tự đặt tên file.
        - Xuất đúng bộ kết quả vừa tính gần nhất.
        - Nếu file đang mở trong Excel, tự đổi sang tên _01, _02...
        """
        try:
            results_to_export = list(
                self.last_hydro_results or []
            )

            if not results_to_export:
                raise Exception(u"Chưa có kết quả thủy tĩnh để xuất.")
            if not self.hydro_results_are_current():
                raise Exception(u"Hình học, mớn nước hoặc khối lượng riêng đã thay đổi; hãy tính lại trước khi xuất Excel.")

            output_path = choose_hydro_xlsx_output_path(
                results_to_export,
                self.last_hydro_result_kind
            )

            if not output_path:
                self.status_label.Text = (
                    u"Đã hủy xuất Excel"
                )

                return

            (
                actual_output_path,
                used_alternate_name
            ) = export_hydrostatic_results_xlsx(
                results_to_export,
                output_path
            )

            self.status_label.Text = (
                u"Đã xuất %d dòng thủy tĩnh" %
                len(results_to_export)
            )

            if used_alternate_name:
                message = (
                    u"Không thể ghi trực tiếp vào file bạn chọn "
                    u"(có thể file đang mở trong Excel hoặc thư mục không có quyền ghi). "
                    u"Model 112 đã tự lưu sang đường dẫn an toàn:\n\n"
                    u"%s\n\n"
                    u"Số mớn nước: %d | Chi tiết kiểm tra ở dưới bảng."
                ) % (
                    actual_output_path,
                    len(results_to_export)
                )
            else:
                message = (
                    u"Đã xuất bảng thủy tĩnh Excel:\n\n%s\n\n"
                    u"Số mớn nước: %d | Chi tiết kiểm tra ở dưới bảng."
                ) % (
                    actual_output_path,
                    len(results_to_export)
                )

            forms.MessageBox.Show(
                message,
                u"Hoàn tất"
            )

        except Exception as error:
            forms.MessageBox.Show(
                u"Không xuất được Excel:\n%s" %
                str(error),
                u"Lỗi xuất dữ liệu"
            )




    def on_mode_changed(self, sender, event):
        """
        Bốn trang luôn tồn tại trong TabControl chính.
        Chuyển trang chỉ cập nhật dữ liệu tóm tắt, không Visible/Hidden layout.
        """
        if not hasattr(
            self,
            "main_pages"
        ):
            return

        page_index = int(
            self.main_pages.SelectedIndex
        )

        self.preview_timer.Stop()

        # SOURCE_3D lấy đúng chế độ nửa/toàn thân tại lúc tạo. Trong trang
        # thiết kế, tạm ẩn nguồn để không chồng lên hình xem trước.
        if page_index == 0:
            if sc.sticky.get(PREVIEW_STICKY_KEY, []):
                self.hide_mode1_background(include_final=True)
            elif self.params.create_half_model:
                self.hide_mode1_background(
                    include_final=sc.sticky.get(
                        FINAL_HULL_IS_HALF_STICKY_KEY
                    ) is not True
                )
            else:
                self.restore_linesplan_source_visibility()
        else:
            self.restore_linesplan_source_visibility()

        if page_index == 0:
            self.status_label.Text = (
                u"Trang 1 - Tạo vỏ tàu"
            )

        elif page_index == 1:
            self.update_linesplan_base_summary()
            self.refresh_coordinate_feature_dropdown()
            self.status_label.Text = (
                u"Trang 2 - Tạo đường hình 2D"
            )

        elif page_index == 2:
            self.update_hydro_base_summary()
            if self.last_hydro_results and not self.hydro_results_are_current():
                self.hydro_quality_label.Text = u"KẾT QUẢ CŨ: tham số đã thay đổi; tính lại trước khi dùng hoặc xuất dữ liệu."
            self.status_label.Text = (
                u"Trang 3 - Tính toán thủy tĩnh"
            )

        elif page_index == 3:
            self.update_survey_base_summary()
            self.update_survey_summary()
            self.status_label.Text = (
                u"Trang 4 - Khảo sát mẫu β × α"
            )


    def on_survey_count_changed(self, sender, event):
        # Bật đúng số ô mà người dùng muốn khảo sát.
        self.update_survey_controls_state()
        self.update_survey_summary()
        self.update_survey_hydro_current_state()
        if hasattr(self, "survey_heatmap_area"):
            self.on_update_survey_heatmap()


    def on_survey_values_changed(self, sender, event):
        # Cập nhật ngay số mẫu và danh sách giá trị khi người dùng sửa một ô.
        self.update_survey_summary()
        self.update_survey_hydro_current_state()
        if hasattr(self, "survey_heatmap_area"):
            self.on_update_survey_heatmap()


    def update_survey_controls_state(self):
        beta_count = int(round(float(self.survey_beta_count.Value)))
        alpha_count = int(round(float(self.survey_alpha_count.Value)))

        for index, control in enumerate(self.survey_beta_inputs):
            control.Enabled = index < beta_count

        for index, control in enumerate(self.survey_alpha_inputs):
            control.Enabled = index < alpha_count


    def update_survey_base_summary(self):
        if not hasattr(
            self,
            "survey_base_summary"
        ):
            return

        units = float(
            self.params.units_per_meter
        )

        link_text = (
            u"Có"
            if self.params.link_deadrise_profile
            else u"Không"
        )

        half_text = (
            u"Nửa mạn Starboard"
            if bool(
                getattr(
                    self.params,
                    "create_half_model",
                    False
                )
            )
            else u"Đủ hai mạn"
        )

        self.survey_base_summary.Text = (
            u"Lmax = {0:.2f} m | Bmax = {1:.2f} m | H = {2:.2f} m | "
            u"T = {3:.2f} m | Số đường gãy = {4:d} | Sườn thân = {5:d} | "
            u"Mặt cắt làm trơn mũi = {6:d} | Liên kết β mũi/đuôi = {7} | "
            u"Chế độ hình học = {8}."
        ).format(
            self.params.length / units,
            self.params.beam / units,
            self.params.depth / units,
            self.params.draft / units,
            int(
                self.params.total_knuckle_count_per_side
            ),
            int(
                self.params.body_station_count
            ),
            int(
                self.params.bow_fairing_section_count
            ),
            link_text,
            half_text
        )

        if hasattr(
            self,
            "survey_hydro_draft_input"
        ):
            try:
                maximum_draft = max(
                    0.001,
                    (
                        float(
                            self.params.depth
                        ) /
                        units
                    ) -
                    0.001
                )

                self.survey_hydro_draft_input.MaxValue = (
                    maximum_draft
                )

                if (
                    hasattr(
                        self,
                        "survey_hydro_use_design_draft"
                    ) and
                    bool(
                        self.survey_hydro_use_design_draft.Checked
                    )
                ):
                    design_draft = (
                        float(
                            self.params.draft
                        ) /
                        units
                    )

                    if design_draft <= maximum_draft:
                        self.survey_hydro_draft_input.Value = (
                            design_draft
                        )
            except Exception:
                pass

            self.update_survey_hydro_current_state()


    def get_survey_beta_values(self):
        count = int(round(float(self.survey_beta_count.Value)))
        return [
            float(self.survey_beta_inputs[index].Value)
            for index in range(count)
        ]


    def get_survey_alpha_values(self):
        count = int(round(float(self.survey_alpha_count.Value)))
        return [
            float(self.survey_alpha_inputs[index].Value)
            for index in range(count)
        ]


    def update_survey_summary(self):
        if not hasattr(self, "survey_matrix_summary"):
            return

        beta_values = self.get_survey_beta_values()
        alpha_values = self.get_survey_alpha_values()
        total_models = len(beta_values) * len(alpha_values)

        beta_text = ", ".join([
            ("%.1f" % value).rstrip("0").rstrip(".")
            for value in beta_values
        ])
        alpha_text = ", ".join([
            ("%.1f" % value).rstrip("0").rstrip(".")
            for value in alpha_values
        ])

        self.survey_matrix_summary.Text = (
            u"Góc vát đáy β (cột): %s\nGóc nghiêng mũi α (hàng): %s\n"
            u"Ma trận khảo sát: %d x %d = %d mẫu (tối đa 100 mẫu)."
        ) % (
            beta_text,
            alpha_text,
            len(beta_values),
            len(alpha_values),
            total_models
        )

        if hasattr(
            self,
            "survey_matrix_preview"
        ):
            self.survey_matrix_preview.Text = (
                format_survey_matrix_preview(
                    beta_values,
                    alpha_values
                )
            )

        self.update_survey_hydro_current_state()


    def on_survey_hydro_draft_mode_changed(
        self,
        sender,
        event
    ):
        use_design = bool(
            self.survey_hydro_use_design_draft.Checked
        )

        self.survey_hydro_draft_input.Enabled = (
            not use_design
        )

        if use_design:
            try:
                self.survey_hydro_draft_input.Value = (
                    float(
                        self.params.draft
                    ) /
                    float(
                        self.params.units_per_meter
                    )
                )
            except Exception:
                pass

        self.update_survey_hydro_current_state()


    def on_survey_hydro_setting_changed(
        self,
        sender,
        event
    ):
        self.update_survey_hydro_current_state()


    def get_survey_hydro_draft_m(self):
        if bool(
            self.survey_hydro_use_design_draft.Checked
        ):
            return (
                float(
                    self.params.draft
                ) /
                float(
                    self.params.units_per_meter
                )
            )

        return float(
            self.survey_hydro_draft_input.Value
        )


    def get_survey_hydro_signature(self):
        if not hasattr(
            self,
            "survey_hydro_density_input"
        ):
            return None

        return (
            build_hull_parameter_signature(
                self.params
            ),
            tuple(
                self.get_survey_beta_values()
            ),
            tuple(
                self.get_survey_alpha_values()
            ),
            round(
                self.get_survey_hydro_draft_m(),
                9
            ),
            round(
                float(
                    self.survey_hydro_density_input.Value
                ),
                9
            )
        )


    def survey_hydro_results_are_current(self):
        if not getattr(
            self,
            "survey_hydro_results",
            None
        ):
            return False

        if self.survey_hydro_signature is None:
            return False

        try:
            return (
                self.survey_hydro_signature
                ==
                self.get_survey_hydro_signature()
            )
        except Exception:
            return False


    def update_survey_hydro_current_state(self):
        if not hasattr(
            self,
            "survey_hydro_summary"
        ):
            return

        if not getattr(
            self,
            "survey_hydro_results",
            None
        ):
            return

        if not self.survey_hydro_results_are_current():
            self.survey_hydro_summary.Text = (
                u"Kết quả Hydro đang hiển thị được tính theo bộ tham số trước đó. "
                u"Đã có thay đổi ở Trang 1, ma trận β × α, T hoặc ρ; "
                u"hãy bấm Tính lại trước khi xuất dữ liệu."
            )


    def on_cancel_survey_hydro(
        self,
        sender,
        event
    ):
        self.survey_hydro_cancel_requested = True
        self.status_label.Text = (
            u"Đã yêu cầu dừng sau mẫu đang tính..."
        )


    def on_calculate_survey_hydro(
        self,
        sender,
        event
    ):
        """
        Tính Hydro tuần tự cho ma trận beta x alpha tại MỘT mớn nước.
        Mỗi mẫu chỉ giữ nguồn Hydro trong thời gian tính mẫu đó.
        """
        self.preview_timer.Stop()
        self.update_survey_base_summary()
        self.update_survey_summary()

        beta_values = self.get_survey_beta_values()
        alpha_values = self.get_survey_alpha_values()
        total_models = (
            len(beta_values) *
            len(alpha_values)
        )

        if total_models < 1 or total_models > 100:
            forms.MessageBox.Show(
                u"Số mẫu phải nằm trong khoảng 1 đến 100.",
                u"Lỗi khảo sát Hydro"
            )
            return

        draft_m = self.get_survey_hydro_draft_m()

        density = float(
            self.survey_hydro_density_input.Value
        )

        depth_m = (
            float(
                self.params.depth
            ) /
            float(
                self.params.units_per_meter
            )
        )

        if draft_m < 0.0:
            forms.MessageBox.Show(
                u"Mớn nước khảo sát không được âm.",
                u"Lỗi khảo sát Hydro"
            )
            return

        if draft_m >= depth_m:
            forms.MessageBox.Show(
                (
                    u"Mớn nước khảo sát phải nhỏ hơn H.\n"
                    u"T = %.3f m | H = %.3f m"
                ) %
                (
                    draft_m,
                    depth_m
                ),
                u"Lỗi khảo sát Hydro"
            )
            return

        if density <= 0.0:
            forms.MessageBox.Show(
                u"Khối lượng riêng phải lớn hơn 0.",
                u"Lỗi khảo sát Hydro"
            )
            return

        original_params = copy.deepcopy(
            self.params
        )

        results = []
        success_count = 0
        error_count = 0
        model_index = 0
        batch_error = None

        self.survey_hydro_results = []
        self.survey_hydro_signature = None
        self.survey_hydro_cancel_requested = False

        self.survey_hydro_report_area.Text = (
            u"Đang tính..."
        )

        self.survey_hydro_summary.Text = (
            (
                u"Đang tính %d mẫu tại T = %.3f m, ρ = %.4f t/m³. "
                u"Phép tính chạy tuần tự."
            ) %
            (
                total_models,
                draft_m,
                density
            )
        )

        self.status_label.Text = (
            u"Đang tính Hydro cho %d mẫu khảo sát..." %
            total_models
        )

        try:
            for row_index, alpha_value in enumerate(
                alpha_values
            ):
                for column_index, beta_value in enumerate(
                    beta_values
                ):
                    if self.survey_hydro_cancel_requested:
                        break

                    model_index += 1

                    Rhino.RhinoApp.SetCommandPrompt(
                        (
                            u"Model 112 - Hydro mẫu %d/%d | beta %.1f | "
                            u"alpha %.1f | T %.3f m"
                        ) %
                        (
                            model_index,
                            total_models,
                            beta_value,
                            alpha_value,
                            draft_m
                        )
                    )

                    survey_params = copy.deepcopy(
                        original_params
                    )

                    survey_params.link_deadrise_profile = False
                    survey_params.deadrise_midship_angle = (
                        beta_value
                    )
                    survey_params.bow_rake_angle = (
                        alpha_value
                    )

                    sync_research_parameters(
                        survey_params
                    )

                    survey_params.export_parameter_table = False
                    survey_params.export_station_table = False

                    before_sample_ids = (
                        all_document_object_ids()
                    )

                    try:
                        param_status, param_notes = v20_parameter_diagnostics(survey_params)
                        if param_status == "INVALID":
                            raise Exception(v20_format_diagnostics(param_status, param_notes))
                        one_result_list = (
                            calculate_hydrostatic_series(
                                survey_params,
                                [
                                    draft_m
                                ],
                                density
                            )
                        )

                        if not one_result_list:
                            raise Exception(
                                u"Engine Hydro không trả kết quả."
                            )

                        row = one_result_list[
                            0
                        ]

                        row[
                            "sample_index"
                        ] = model_index
                        row[
                            "beta_deg"
                        ] = beta_value
                        row[
                            "alpha_deg"
                        ] = alpha_value
                        hydro_status, quality_note = hydro_result_quality(row)
                        hydro_notes = []
                        if hydro_status == "WARNING":
                            hydro_notes.append(quality_note)
                        if param_status == "WARNING":
                            hydro_status = "WARNING"
                            hydro_notes.append(v20_format_diagnostics(param_status, param_notes))
                        row[
                            "status"
                        ] = hydro_status
                        row["diagnostic_message"] = u"; ".join(hydro_notes)
                        row[
                            "error_message"
                        ] = ""

                        results.append(
                            row
                        )

                        success_count += 1

                    except Exception as error:
                        delete_document_objects_created_since(
                            before_sample_ids
                        )

                        results.append(
                            {
                                "sample_index": model_index,
                                "beta_deg": beta_value,
                                "alpha_deg": alpha_value,
                                "draft_m": draft_m,
                                "density_t_m3": density,
                                "status": "INVALID",
                                "error_message": TEXT_TYPE(
                                    error
                                )
                            }
                        )

                        error_count += 1

                        Rhino.RhinoApp.WriteLine(
                            (
                                "Model 112 survey Hydro sample %d error: %s"
                            ) %
                            (
                                model_index,
                                str(
                                    error
                                )
                            )
                        )

                    if (
                        model_index == 1 or
                        model_index % 5 == 0 or
                        model_index == total_models
                    ):
                        self.survey_hydro_results = list(
                            results
                        )

                        self.survey_hydro_summary.Text = (
                            (
                                u"Tiến độ: %d/%d | Thành công: %d | Lỗi: %d | "
                                u"T = %.3f m"
                            ) %
                            (
                                model_index,
                                total_models,
                                success_count,
                                error_count,
                                draft_m
                            )
                        )

                        self.survey_hydro_report_area.Text = (
                            format_survey_hydro_report_table(
                                results
                            )
                        )

                    Rhino.RhinoApp.Wait()

                    if (
                        model_index % 10 == 0
                    ):
                        try:
                            System.GC.Collect()
                        except Exception:
                            pass

                if self.survey_hydro_cancel_requested:
                    break

        except Exception as error:
            batch_error = TEXT_TYPE(
                error
            )

            Rhino.RhinoApp.WriteLine(
                (
                    "Model 112 survey Hydro batch error: %s"
                ) %
                str(
                    error
                )
            )

        finally:
            apply_parameter_bindings(
                copy.deepcopy(
                    original_params
                )
            )

        self.survey_hydro_results = list(
            results
        )

        self.survey_hydro_signature = (
            self.get_survey_hydro_signature()
        )

        self.survey_hydro_report_area.Text = (
            format_survey_hydro_report_table(
                self.survey_hydro_results
            )
        )
        self.on_update_survey_heatmap()

        if batch_error is not None:
            self.survey_hydro_summary.Text = (
                (
                    u"Batch bị dừng ngoài dự kiến sau %d/%d mẫu. "
                    u"Thành công: %d | Lỗi mẫu: %d\n%s"
                ) %
                (
                    len(results),
                    total_models,
                    success_count,
                    error_count,
                    batch_error
                )
            )

            self.status_label.Text = (
                u"Hydro khảo sát bị dừng do lỗi"
            )

            Rhino.RhinoApp.SetCommandPrompt(
                u"Model 112 - Hydro khảo sát bị dừng do lỗi"
            )

        elif self.survey_hydro_cancel_requested:
            self.survey_hydro_summary.Text = (
                (
                    u"Đã dừng theo yêu cầu tại %d/%d mẫu | "
                    u"Thành công: %d | Lỗi: %d | T = %.3f m"
                ) %
                (
                    len(results),
                    total_models,
                    success_count,
                    error_count,
                    draft_m
                )
            )

            self.status_label.Text = (
                u"Đã dừng Hydro khảo sát"
            )

            Rhino.RhinoApp.SetCommandPrompt(
                u"Model 112 - đã dừng Hydro khảo sát"
            )

        else:
            self.survey_hydro_summary.Text = (
                (
                    u"Hoàn tất %d mẫu | Thành công: %d | Lỗi: %d | "
                    u"T = %.3f m | ρ = %.4f t/m³"
                ) %
                (
                    total_models,
                    success_count,
                    error_count,
                    draft_m,
                    density
                )
            )

            self.status_label.Text = (
                u"Đã tính Hydro cho %d mẫu khảo sát" %
                total_models
            )

            Rhino.RhinoApp.SetCommandPrompt(
                (
                    u"Model 112 - hoàn tất Hydro %d mẫu tại T %.3f m"
                ) %
                (
                    total_models,
                    draft_m
                )
            )


    def on_export_survey_hydro_csv(
        self,
        sender,
        event
    ):
        if not getattr(
            self,
            "survey_hydro_results",
            None
        ):
            forms.MessageBox.Show(
                u"Chưa có kết quả Hydro khảo sát để xuất.",
                u"MODEL 112"
            )
            return

        if not self.survey_hydro_results_are_current():
            forms.MessageBox.Show(
                (
                    u"Bộ tham số đã thay đổi sau lần tính Hydro.\n"
                    u"Hãy tính lại ma trận trước khi xuất để tránh dùng dữ liệu cũ."
                ),
                u"MODEL 112"
            )
            return

        output_path = (
            choose_survey_hydro_csv_output_path(
                self.survey_hydro_results
            )
        )

        if not output_path:
            return

        try:
            actual_path, renamed = (
                export_survey_hydro_results(
                    self.survey_hydro_results,
                    output_path
                )
            )

            if renamed:
                message = (
                    u"Đã xuất bảng Hydro khảo sát.\n"
                    u"File gốc không thể ghi hoặc đã tồn tại, "
                    u"nên MODEL 112 dùng tên an toàn:\n\n%s"
                ) % actual_path
            else:
                message = (
                    u"Đã xuất bảng Hydro khảo sát:\n\n%s"
                ) % actual_path

            forms.MessageBox.Show(
                message,
                u"MODEL 112"
            )

            self.status_label.Text = (
                u"Đã xuất CSV Hydro khảo sát"
            )

        except Exception as error:
            forms.MessageBox.Show(
                (
                    u"Không thể xuất bảng Hydro khảo sát:\n%s"
                ) %
                TEXT_TYPE(
                    error
                ),
                u"MODEL 112"
            )

            self.status_label.Text = (
                u"Xuất CSV Hydro khảo sát thất bại"
            )


    def build_footer(self):
        # Footer này chỉ thuộc Chế độ 1.
        layout = forms.DynamicLayout()
        layout.Spacing = drawing.Size(8, 0)

        preview_button = forms.Button(
            Text=u"Xem trước"
        )
        preview_button.Click += self.on_preview

        generate_button = forms.Button(
            Text=u"Tạo vỏ tàu"
        )
        generate_button.Click += self.on_generate_final

        clear_preview_button = forms.Button(
            Text=u"Xóa hình xem trước"
        )
        clear_preview_button.Click += self.on_clear_preview

        reset_button = forms.Button(
            Text=u"Đặt lại tham số"
        )
        reset_button.Click += self.on_reset

        layout.AddRow(
            self.live_preview_check,
            preview_button,
            generate_button,
            clear_preview_button,
            reset_button,
            None
        )

        return layout


    def get_slider_max(
        self,
        spec
    ):
        return int(
            round(
                (
                    spec.maximum -
                    spec.minimum
                ) /
                spec.step
            )
        )


    def get_display_value(
        self,
        spec
    ):
        stored_value = getattr(
            self.params,
            spec.key
        )

        return (
            float(stored_value) /
            float(spec.display_scale)
        )


    def display_value_to_slider(
        self,
        spec,
        display_value
    ):
        slider_value = int(
            round(
                (
                    float(display_value) -
                    spec.minimum
                ) /
                spec.step
            )
        )

        return max(
            0,
            min(
                self.get_slider_max(
                    spec
                ),
                slider_value
            )
        )


    def slider_to_display_value(
        self,
        spec,
        slider_value
    ):
        display_value = (
            spec.minimum +
            float(slider_value) *
            spec.step
        )

        return max(
            spec.minimum,
            min(
                spec.maximum,
                display_value
            )
        )


    def set_parameter_from_display(
        self,
        spec,
        display_value
    ):
        display_value = max(
            spec.minimum,
            min(
                spec.maximum,
                float(display_value)
            )
        )

        stored_value = (
            display_value *
            spec.display_scale
        )

        if spec.key in (
            "total_knuckle_count_per_side",
            "body_station_count",
            "bow_fairing_section_count"
        ):
            stored_value = int(
                round(
                    stored_value
                )
            )

        setattr(
            self.params,
            spec.key,
            stored_value
        )

        sync_research_parameters(
            self.params
        )


    def refresh_parameter_control(
        self,
        key
    ):
        if key not in self.parameter_controls:
            return

        controls = (
            self.parameter_controls[
                key
            ]
        )
        spec = controls["spec"]
        display_value = self.get_display_value(
            spec
        )

        self.updating_controls = True

        controls["numeric"].Value = (
            display_value
        )
        controls["slider"].Value = (
            self.display_value_to_slider(
                spec,
                display_value
            )
        )

        self.updating_controls = False


    def refresh_all_controls(self):
        for key in self.parameter_controls:
            self.refresh_parameter_control(
                key
            )

        self.link_profile_check.Checked = (
            self.params.link_deadrise_profile
        )
        self.half_model_check.Checked = bool(
            getattr(
                self.params,
                "create_half_model",
                False
            )
        )

        self.show_keel_check.Checked = bool(
            getattr(
                self.params,
                "show_keel_curve",
                self.params.show_longitudinal_curves
            )
        )
        self.show_chine_check.Checked = bool(
            getattr(
                self.params,
                "show_chine_curves",
                self.params.show_longitudinal_curves
            )
        )
        self.show_sheer_check.Checked = bool(
            getattr(
                self.params,
                "show_sheer_curve",
                self.params.show_longitudinal_curves
            )
        )

        self.show_body_stations_check.Checked = (
            self.params.show_body_stations
        )
        self.show_bow_sections_check.Checked = (
            self.params.show_bow_fairing_sections
        )
        self.show_design_points_check.Checked = (
            self.params.show_design_points
        )
        self.show_waterline_check.Checked = (
            self.params.create_design_waterline
        )
        self.show_transom_frame_check.Checked = bool(
            getattr(
                self.params,
                "show_transom_frame",
                True
            )
        )

        self.create_hull_check.Checked = (
            self.params.create_hull_surfaces
        )
        self.create_transom_check.Checked = (
            self.params.create_transom_surfaces
        )
        self.create_deck_check.Checked = (
            self.params.create_deck_surface
        )

        self.separate_surfaces_check.Checked = (
            not bool(
                self.params.join_hull_surfaces
            )
        )

        self.group_framework_check.Checked = (
            bool(
                self.params.group_framework_only
            )
        )

        self.export_parameter_check.Checked = (
            self.params.export_parameter_table
        )
        self.export_station_check.Checked = (
            self.params.export_station_table
        )

        self.apply_link_profile_state()


    def on_numeric_changed(
        self,
        key
    ):
        if self.updating_controls:
            return

        controls = (
            self.parameter_controls[
                key
            ]
        )
        spec = controls["spec"]

        self.set_parameter_from_display(
            spec,
            controls["numeric"].Value
        )

        self.updating_controls = True
        controls["slider"].Value = (
            self.display_value_to_slider(
                spec,
                controls["numeric"].Value
            )
        )
        self.updating_controls = False

        if (
            key ==
            "deadrise_midship_angle" and
            self.params.link_deadrise_profile
        ):
            self.refresh_parameter_control(
                "deadrise_stern_angle"
            )
            self.refresh_parameter_control(
                "deadrise_bow_angle"
            )

        self.update_survey_base_summary()
        self.schedule_live_preview()


    def on_slider_changed(
        self,
        key
    ):
        if self.updating_controls:
            return

        controls = (
            self.parameter_controls[
                key
            ]
        )
        spec = controls["spec"]

        display_value = (
            self.slider_to_display_value(
                spec,
                controls["slider"].Value
            )
        )

        self.updating_controls = True
        controls["numeric"].Value = (
            display_value
        )
        self.updating_controls = False

        self.set_parameter_from_display(
            spec,
            display_value
        )

        if (
            key ==
            "deadrise_midship_angle" and
            self.params.link_deadrise_profile
        ):
            self.refresh_parameter_control(
                "deadrise_stern_angle"
            )
            self.refresh_parameter_control(
                "deadrise_bow_angle"
            )

        self.update_survey_base_summary()
        self.schedule_live_preview()


    def on_link_profile_changed(
        self,
        sender,
        event
    ):
        self.params.link_deadrise_profile = bool(
            self.link_profile_check.Checked
        )

        sync_research_parameters(
            self.params
        )

        self.refresh_parameter_control(
            "deadrise_stern_angle"
        )
        self.refresh_parameter_control(
            "deadrise_bow_angle"
        )

        self.apply_link_profile_state()
        self.update_survey_base_summary()
        self.schedule_live_preview()


    def apply_link_profile_state(self):
        enabled = not bool(
            self.params.link_deadrise_profile
        )

        for key in [
            "deadrise_stern_angle",
            "deadrise_bow_angle"
        ]:
            if key in self.parameter_controls:
                self.parameter_controls[
                    key
                ]["numeric"].Enabled = enabled

                self.parameter_controls[
                    key
                ]["slider"].Enabled = enabled


    def on_half_model_changed(
        self,
        sender,
        event
    ):
        self.params.create_half_model = bool(
            self.half_model_check.Checked
        )

        # Xóa Preview kiểu cũ ngay khi đổi toàn thân/nửa thân. Nếu nguồn
        # đường hình Mode 2 đang hiện, tạm ẩn để không lẫn vào nửa thân.
        self.preview_timer.Stop()
        clear_sticky_objects(PREVIEW_STICKY_KEY)
        self.restore_preview_background()
        if self.params.create_half_model:
            self.hide_mode1_background(
                include_final=sc.sticky.get(FINAL_HULL_IS_HALF_STICKY_KEY) is not True
            )

        self.update_survey_base_summary()
        self.update_linesplan_base_summary()
        self.schedule_live_preview()


    def hide_mode1_background(self, include_final=False):
        """Giữ nguồn Mode 2/toàn thân cũ khỏi chồng lên Preview nửa thân."""
        if include_final:
            self._hidden_preview_final_ids.extend(
                hide_visible_model112_objects_temporarily(
                    sc.sticky.get(FINAL_HULL_OBJECTS_STICKY_KEY, [])
                )
            )
        if self.params.create_half_model:
            self._hidden_linesplan_source_ids.extend(
                hide_visible_model112_objects_temporarily(
                    model112_linesplan_source_object_ids()
                )
            )
        else:
            self.restore_linesplan_source_visibility()


    def restore_linesplan_source_visibility(self):
        restore_temporarily_hidden_model112_objects(
            self._hidden_linesplan_source_ids
        )
        self._hidden_linesplan_source_ids = []
        sc.sticky[HIDDEN_LINESPLAN_SOURCE_STICKY_KEY] = []


    def restore_preview_background(self):
        restore_temporarily_hidden_model112_objects(
            self._hidden_preview_final_ids
        )
        self._hidden_preview_final_ids = []
        self.restore_linesplan_source_visibility()



    def on_display_changed(
        self,
        sender,
        event
    ):
        self.params.show_keel_curve = bool(
            self.show_keel_check.Checked
        )
        self.params.show_chine_curves = bool(
            self.show_chine_check.Checked
        )
        self.params.show_sheer_curve = bool(
            self.show_sheer_check.Checked
        )

        # Biến cũ được giữ làm master compatibility.
        self.params.show_longitudinal_curves = bool(
            self.params.show_keel_curve or
            self.params.show_chine_curves or
            self.params.show_sheer_curve
        )

        self.params.show_body_stations = bool(
            self.show_body_stations_check.Checked
        )
        self.params.show_bow_fairing_sections = bool(
            self.show_bow_sections_check.Checked
        )
        self.params.show_design_points = bool(
            self.show_design_points_check.Checked
        )
        self.params.create_design_waterline = bool(
            self.show_waterline_check.Checked
        )
        self.params.show_transom_frame = bool(
            self.show_transom_frame_check.Checked
        )

        self.params.create_hull_surfaces = bool(
            self.create_hull_check.Checked
        )
        self.params.create_transom_surfaces = bool(
            self.create_transom_check.Checked
        )
        self.params.create_deck_surface = bool(
            self.create_deck_check.Checked
        )

        # Checked = giữ Surface rời -> JoinHullSurfaces = False.
        self.params.join_hull_surfaces = not bool(
            self.separate_surfaces_check.Checked
        )

        self.params.group_framework_only = bool(
            self.group_framework_check.Checked
        )

        self.params.export_parameter_table = bool(
            self.export_parameter_check.Checked
        )
        self.params.export_station_table = bool(
            self.export_station_check.Checked
        )

        self.schedule_live_preview()


    def schedule_live_preview(self):
        if not bool(
            self.live_preview_check.Checked
        ):
            return

        self.preview_timer.Stop()
        self.preview_timer.Start()


    def on_preview_timer(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        self.create_preview()


    def build_preview_params(self):
        preview_params = copy.deepcopy(
            self.params
        )

        preview_params.export_parameter_table = False
        preview_params.export_station_table = False

        return preview_params


    def create_preview(self):
        diag_status, diag_items = v20_parameter_diagnostics(self.params)
        self.diagnostic_label.Text = v20_format_diagnostics(diag_status, diag_items)
        if diag_status == "INVALID":
            self.status_label.Text = u"Không tạo Preview: tham số/hình học không hợp lệ"
            return
        self.status_label.Text = (
            u"Đang tạo hình xem trước..."
        )

        before_ids = all_document_object_ids()

        try:
            self.hide_mode1_background(include_final=True)
            generate_hull(
                self.build_preview_params(),
                sticky_key=PREVIEW_STICKY_KEY,
                clear_sticky=True
            )
            self.status_label.Text = (
                u"Đã cập nhật hình xem trước"
            )
        except Exception as error:
            delete_document_objects_created_since(
                before_ids
            )
            self.restore_preview_background()
            self.status_label.Text = (
                u"Tạo hình xem trước thất bại"
            )
            Rhino.RhinoApp.WriteLine(
                "Model 112 preview error: %s" %
                str(error)
            )


    def on_preview(
        self,
        sender,
        event
    ):
        self.create_preview()


    def on_generate_final(
        self,
        sender,
        event
    ):
        diag_status, diag_items = v20_parameter_diagnostics(self.params)
        self.diagnostic_label.Text = v20_format_diagnostics(diag_status, diag_items)
        if diag_status == "INVALID":
            self.status_label.Text = u"Không tạo vỏ: tham số/hình học không hợp lệ"
            return
        self.preview_timer.Stop()
        clear_sticky_objects(
            PREVIEW_STICKY_KEY
        )

        self.status_label.Text = (
            u"Đang tạo vỏ tàu..."
        )

        before_ids = all_document_object_ids()
        previous_final_ids = list(
            sc.sticky.get(
                FINAL_HULL_OBJECTS_STICKY_KEY,
                []
            ) or []
        )

        try:
            final_result = generate_hull(
                copy.deepcopy(
                    self.params
                ),
                group_name=(
                    "Model112_Beta_%02d_Alpha_%02d" %
                    (
                        int(
                            round(
                                self.params.deadrise_midship_angle
                            )
                        ),
                        int(
                            round(
                                self.params.bow_rake_angle
                            )
                        )
                    )
                ),
                register_linesplan_sources=True
            )

            # Chỉ xóa vỏ cuối cũ SAU KHI vỏ mới đã tạo thành công.
            # Nhờ vậy nếu V19 gặp lỗi giữa chừng, mô hình trước vẫn còn nguyên.
            delete_object_ids(
                previous_final_ids
            )
            self._hidden_preview_final_ids = []
            if not self.params.create_half_model:
                self.restore_linesplan_source_visibility()

            sc.sticky[
                FINAL_HULL_OBJECTS_STICKY_KEY
            ] = list(
                final_result.get(
                    "object_ids",
                    []
                )
            )
            sc.sticky[FINAL_HULL_IS_HALF_STICKY_KEY] = bool(
                self.params.create_half_model
            )

            sc.sticky[
                FINAL_HULL_LINES_STICKY_KEY
            ] = final_result.get(
                "hull_line_data",
                {}
            )

            self.status_label.Text = (
                u"Đã tạo vỏ tàu"
            )
        except Exception as error:
            delete_document_objects_created_since(
                before_ids
            )
            self.restore_preview_background()
            self.status_label.Text = (
                u"Tạo vỏ tàu thất bại"
            )
            Rhino.RhinoApp.WriteLine(
                "Model 112 generation error: %s" %
                str(error)
            )


    def on_clear_preview(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        clear_sticky_objects(
            PREVIEW_STICKY_KEY
        )
        self.restore_preview_background()
        sc.doc.Views.Redraw()
        self.status_label.Text = (
            u"Đã xóa hình xem trước"
        )


    def get_survey_geometry_signature(self):
        return (
            build_hull_parameter_signature(self.params),
            tuple(self.get_survey_beta_values()),
            tuple(self.get_survey_alpha_values())
        )

    def on_export_survey_geometry_csv(self, sender, event):
        if not self.survey_geometry_results:
            forms.MessageBox.Show(u"Chưa có kết quả so sánh hình học.", u"MODEL 112")
            return
        if self.survey_geometry_signature != self.get_survey_geometry_signature():
            forms.MessageBox.Show(u"Tham số khảo sát đã thay đổi; hãy tạo lại mẫu trước khi xuất.", u"MODEL 112")
            return
        path = rs.SaveFileName(u"Xuất so sánh hình học", u"CSV (*.csv)|*.csv||",
                               get_data_output_directory(), "Model112_khaosat_hinhhoc.csv", "csv")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".csv"
        if os.path.exists(path):
            path = make_duplicate_safe_path(path)
        keys = ("sample_index", "beta_deg", "alpha_deg", "status", "drms_m",
                "dmax_m", "dx_rms_m", "dy_rms_m", "dz_rms_m",
                "beta_at_x_ratio", "beta_expected_deg", "beta_measured_deg",
                "beta_error_deg", "alpha_measured_deg",
                "alpha_error_deg", "message")
        def csv_cell(value):
            return u'"' + TEXT_TYPE(value if value is not None else u"").replace(u'"', u'""') + u'"'
        lines = [u"sep=,", u",".join(csv_cell(k) for k in keys)]
        for row in self.survey_geometry_results:
            lines.append(u",".join(csv_cell(row.get(k, u"")) for k in keys))
        try:
            with open(path, "wb") as output:
                output.write(b"\xef\xbb\xbf")
                output.write((u"\r\n".join(lines) + u"\r\n").encode("utf-8"))
            self.status_label.Text = u"Đã xuất %d dòng so sánh hình học." % len(self.survey_geometry_results)
        except Exception as error:
            forms.MessageBox.Show(u"Không xuất được CSV: %s" % TEXT_TYPE(error), u"MODEL 112")


    def on_clear_survey_sections(self, sender=None, event=None):
        clear_sticky_objects("MODEL112_SURVEY_SECTION_OVERLAY")
        if hasattr(self, "section_overlay_report"):
            self.section_overlay_report.Text = u"Đã xóa tiết diện so sánh."
        sc.doc.Views.Redraw()

    def on_overlay_survey_sections(self, sender, event):
        """Giao Brep thật với bốn mặt phẳng X rồi đặt đường cắt cùng vị trí."""
        if (not self.survey_model_surfaces or
                self.survey_geometry_signature != self.get_survey_geometry_signature()):
            self.section_overlay_report.Text = u"Ma trận hình học chưa được tạo hoặc đã cũ. Hãy tạo lại mẫu trước."
            return
        beta_values = self.get_survey_beta_values()
        alpha_values = self.get_survey_alpha_values()
        mode = int(self.section_comparison_mode.SelectedIndex or 0)
        if mode == 0:
            fixed = float(self.section_fixed_alpha.Value)
            if not any(abs(float(v) - fixed) < 1e-6 for v in alpha_values):
                self.section_overlay_report.Text = u"α cố định phải trùng một giá trị α trong ma trận."
                return
            choices = [(b, fixed) for b in beta_values]
        else:
            fixed = float(self.section_fixed_beta.Value)
            if not any(abs(float(v) - fixed) < 1e-6 for v in beta_values):
                self.section_overlay_report.Text = u"β cố định phải trùng một giá trị β trong ma trận."
                return
            choices = [(fixed, a) for a in alpha_values]
        self.on_clear_survey_sections()
        units = float(self.params.units_per_meter)
        length = float(self.params.length)
        beam = float(self.params.beam)
        tolerance = get_linesplan_intersection_tolerance(units)
        overlay_start = length * (len(beta_values) + 1.5) * self.params.survey_spacing_x_factor
        palette = [(25,85,180),(210,65,52),(25,145,95),(151,78,188),(219,140,38),
                   (55,140,168),(154,102,55),(210,72,140),(85,112,40),(70,70,70)]
        section_positions = (0.25, 0.50, 0.75, 0.85)
        overlay_ids = []
        count = 0
        missing = 0
        layer = rs.AddLayer("MODEL112_SECTION_MORPHING")
        try:
            for index, (beta, alpha) in enumerate(choices):
                key = (round(float(beta), 6), round(float(alpha), 6))
                entry = self.survey_model_surfaces.get(key)
                if not entry:
                    missing += 1
                    continue
                breps = []
                for object_id in entry["surface_ids"]:
                    obj = sc.doc.Objects.FindId(object_id)
                    if obj is not None and isinstance(obj.Geometry, rg.Brep):
                        breps.append(obj.Geometry)
                if not breps:
                    missing += 1
                    continue
                color = System.Drawing.Color.FromArgb(*palette[index % len(palette)])
                x_shift = float(entry["column"]) * length * self.params.survey_spacing_x_factor
                y_shift = float(entry["row"]) * beam * self.params.survey_spacing_y_factor
                for section_index, ratio in enumerate(section_positions):
                    section_x = ratio * length + x_shift
                    plane = rg.Plane(rg.Point3d(section_x, y_shift, 0.0), rg.Vector3d.XAxis)
                    curves = intersect_hull_breps_with_plane(breps, plane, tolerance)
                    target_x = overlay_start + section_index * 1.7 * beam
                    move = rg.Transform.Translation(target_x - section_x, -y_shift, 0.0)
                    for curve in curves:
                        moved = curve.DuplicateCurve()
                        moved.Transform(move)
                        object_id = sc.doc.Objects.AddCurve(moved)
                        if object_id != System.Guid.Empty:
                            rs.ObjectLayer(object_id, layer)
                            rs.ObjectColor(object_id, color)
                            overlay_ids.append(object_id)
                            count += 1
            for section_index, ratio in enumerate(section_positions):
                dot = rs.AddTextDot(u"x/L = %.2f" % ratio,
                    rg.Point3d(overlay_start + section_index * 1.7 * beam,
                               -0.6 * beam, self.params.depth + self.params.baseline_z))
                if dot: rs.ObjectLayer(dot, layer); overlay_ids.append(dot)
            for index, (beta, alpha) in enumerate(choices):
                dot = rs.AddTextDot(u"β %.1f° | α %.1f°" % (beta, alpha),
                    rg.Point3d(overlay_start - 0.4 * beam, -(index + 1) * 0.28 * beam,
                               self.params.depth + self.params.baseline_z))
                if dot: rs.ObjectLayer(dot, layer); overlay_ids.append(dot)
            sc.sticky["MODEL112_SURVEY_SECTION_OVERLAY"] = overlay_ids
            sc.doc.Views.Redraw()
            self.section_overlay_report.Text = (
                u"Đã chồng %d đoạn đường cắt từ %d mẫu. Thiếu bề mặt ở %d mẫu. "
                u"Màu và nhãn phân biệt β/α; đường cắt đặt cạnh ma trận khảo sát."
                % (count, len(choices), missing))
        except Exception as error:
            delete_object_ids(overlay_ids)
            self.section_overlay_report.Text = u"Không tạo được chồng tiết diện: %s" % TEXT_TYPE(error)


    def get_survey_heatmap_selection(self):
        beta_values = self.get_survey_beta_values()
        alpha_values = self.get_survey_alpha_values()
        idx = int(self.survey_heatmap_metric.SelectedIndex) if self.survey_heatmap_metric.SelectedIndex is not None else 0
        options = [
            ("volume_m3", u"V (m³)", self.survey_hydro_results),
            ("lcb_m", u"LCB (m)", self.survey_hydro_results),
            ("kb_m", u"KB (m)", self.survey_hydro_results),
            ("awp_m2", u"Awp (m²)", self.survey_hydro_results),
            ("wetted_m2", u"S (m²)", self.survey_hydro_results),
            ("cb", u"Cb", self.survey_hydro_results),
            ("cwp", u"Cwp", self.survey_hydro_results),
            ("bmt_m", u"BMt (m)", self.survey_hydro_results),
            ("drms_m", u"DRMS (m)", self.survey_geometry_results)
        ]
        idx=max(0,min(len(options)-1,idx))
        key,title,rows=options[idx]
        return beta_values, alpha_values, idx, key, title, rows


    def on_update_survey_heatmap(self, sender=None, event=None):
        beta_values, alpha_values, idx, key, title, rows = (
            self.get_survey_heatmap_selection())
        if idx < 8 and rows and not self.survey_hydro_results_are_current():
            self.survey_heatmap_area.Content = forms.Label(
                Text=u"Dữ liệu thủy tĩnh đã cũ; hãy tính lại ma trận β × α trước khi xem biểu đồ.")
            return
        if (idx == 8 and rows and
                self.survey_geometry_signature != self.get_survey_geometry_signature()):
            self.survey_heatmap_area.Content = forms.Label(
                Text=u"Dữ liệu hình học đã cũ; hãy tạo lại các mẫu trước khi xem biểu đồ DRMS.")
            return
        self.survey_heatmap_area.Content = v20_build_heatmap_grid(
            beta_values, alpha_values, rows, key, title)
        self.survey_heatmap_area.Height = min(
            620, max(250, (len(beta_values) + 2) * 53))


    def on_export_survey_heatmap(self, extension):
        beta_values, alpha_values, idx, key, title, rows = (
            self.get_survey_heatmap_selection())
        if idx < 8 and not self.survey_hydro_results_are_current():
            forms.MessageBox.Show(
                u"Hãy tính lại thủy tĩnh cho ma trận hiện tại trước khi xuất biểu đồ.",
                u"MODEL 112")
            return
        if (idx == 8 and
                self.survey_geometry_signature != self.get_survey_geometry_signature()):
            forms.MessageBox.Show(
                u"Hãy tạo lại các mẫu 3D cho ma trận hiện tại trước khi xuất DRMS.",
                u"MODEL 112")
            return
        _, bounds = v20_collect_heatmap_data(
            beta_values, alpha_values, rows, key)
        if bounds[0] is None:
            forms.MessageBox.Show(
                u"Chưa có kết quả số cho đại lượng đã chọn.", u"MODEL 112")
            return
        path = v20_heatmap_export_path(extension, key)
        if not path:
            return
        try:
            if extension == "png":
                v20_export_heatmap_png(path, beta_values, alpha_values,
                                       rows, key, title)
            else:
                v20_export_heatmap_xlsx(path, beta_values, alpha_values,
                                        rows, key, title)
            self.status_label.Text = u"Đã xuất biểu đồ %s" % extension.upper()
            forms.MessageBox.Show(u"Đã xuất biểu đồ lưới:\n%s" % path,
                                  u"MODEL 112")
        except Exception as error:
            forms.MessageBox.Show(
                u"Không xuất được biểu đồ %s:\n%s" %
                (extension.upper(), TEXT_TYPE(error)), u"MODEL 112")


    def on_export_survey_heatmap_png(self, sender, event):
        self.on_export_survey_heatmap("png")


    def on_export_survey_heatmap_excel(self, sender, event):
        self.on_export_survey_heatmap("xlsx")


    def on_generate_survey(
        self,
        sender,
        event
    ):
        # ---------------------------------------------------------------------
        # Đây là điểm quan trọng nhất của Chế độ 4:
        # 1) Lấy self.params HIỆN TẠI của Chế độ 1.
        # 2) Sao chép sâu cho từng mẫu để không làm thay đổi cấu hình gốc.
        # 3) Chỉ ghi đè deadrise_midship_angle và bow_rake_angle.
        # 4) Góc vát đáy tại mũi và đuôi giữ nguyên theo cấu hình Chế độ 1;
        #    khảo sát không tự liên kết hai giá trị này theo beta giữa tàu.
        # 5) Mọi tham số khác (L, B, H, T, chine, sheer, transom, station...)
        #    đều kế thừa đúng giá trị mới nhất của Chế độ 1.
        # ---------------------------------------------------------------------
        self.preview_timer.Stop()
        clear_sticky_objects(SURVEY_STICKY_KEY)
        self.on_clear_survey_sections()
        self.survey_model_surfaces = {}

        self.update_survey_base_summary()

        beta_values = self.get_survey_beta_values()
        alpha_values = self.get_survey_alpha_values()
        total_models = len(beta_values) * len(alpha_values)

        if total_models < 1 or total_models > 100:
            forms.MessageBox.Show(
                u"Số mẫu phải nằm trong khoảng 1 đến 100.",
                u"Lỗi khảo sát"
            )
            return

        all_survey_ids = []
        model_index = 0
        self.survey_geometry_results = []
        self.survey_geometry_signature = self.get_survey_geometry_signature()
        reference_records = []

        # Tạo một mẫu nền tạm từ đúng bộ tham số Trang 1 để lấy các điểm tương ứng.
        reference_params = copy.deepcopy(self.params)
        reference_params.export_parameter_table = False
        reference_params.export_station_table = False
        reference_before_ids = all_document_object_ids()
        try:
            reference_result = generate_hull(reference_params)
            reference_records = list(reference_result.get("station_records", []))
        finally:
            delete_document_objects_created_since(reference_before_ids)

        self.status_label.Text = (
            u"Đang tạo %d mẫu khảo sát..." % total_models
        )

        try:
            # Alpha là hàng (trục Y), beta là cột (trục X).
            for row_index, alpha_value in enumerate(alpha_values):
                for column_index, beta_value in enumerate(beta_values):
                    model_index += 1

                    Rhino.RhinoApp.SetCommandPrompt(
                        (
                            u"Model 112 - mẫu %d/%d | beta %.1f | alpha %.1f"
                        ) % (
                            model_index,
                            total_models,
                            beta_value,
                            alpha_value
                        )
                    )

                    # Sao chép toàn bộ cấu hình MỚI NHẤT từ Chế độ 1.
                    survey_params = copy.deepcopy(self.params)

                    # Chỉ hai tham số khảo sát được ghi đè.
                    # Beta mũi và beta đuôi giữ nguyên như Chế độ 1.
                    survey_params.link_deadrise_profile = False
                    survey_params.deadrise_midship_angle = beta_value
                    survey_params.bow_rake_angle = alpha_value

                    sync_research_parameters(survey_params)

                    # Tránh xuất hàng trăm file CSV trùng tên khi khảo sát.
                    # Đây chỉ là tắt xuất dữ liệu, KHÔNG làm thay đổi hình học tàu.
                    survey_params.export_parameter_table = False
                    survey_params.export_station_table = False

                    # Bố trí dạng lưới: beta theo X, alpha theo Y.
                    translation = rg.Transform.Translation(
                        float(column_index) *
                        survey_params.length *
                        survey_params.survey_spacing_x_factor,
                        float(row_index) *
                        survey_params.beam *
                        survey_params.survey_spacing_y_factor,
                        0.0
                    )

                    group_name = (
                        "Model112_M%03d_Beta_%s_Alpha_%s" % (
                            model_index,
                            ("%.2f" % beta_value).rstrip("0").rstrip("."),
                            ("%.2f" % alpha_value).rstrip("0").rstrip(".")
                        )
                    )

                    sample_status, sample_diag = v20_parameter_diagnostics(survey_params)
                    before_sample_ids = all_document_object_ids()

                    if sample_status == "INVALID":
                        self.survey_geometry_results.append({
                            "sample_index": model_index, "beta_deg": beta_value, "alpha_deg": alpha_value,
                            "status": "INVALID", "message": v20_format_diagnostics(sample_status, sample_diag)
                        })
                        continue

                    try:
                        result = generate_hull(
                            survey_params,
                            transform=translation,
                            group_name=group_name
                        )
                    except Exception:
                        delete_document_objects_created_since(
                            before_sample_ids
                        )
                        raise

                    all_survey_ids.extend(
                        result["object_ids"]
                    )
                    _, surface_ids = split_created_ids_by_geometry_type(result["object_ids"])
                    self.survey_model_surfaces[(round(float(beta_value), 6),
                                                round(float(alpha_value), 6))] = {
                        "surface_ids": surface_ids,
                        "column": column_index,
                        "row": row_index
                    }

                    geometry_row = {
                        "sample_index": model_index,
                        "beta_deg": beta_value,
                        "alpha_deg": alpha_value,
                        "status": sample_status
                    }
                    geometry_row.update(
                        v20_geometry_metrics_from_station_records(
                            reference_records,
                            result.get("station_records", []),
                            survey_params
                        )
                    )
                    try:
                        alpha_measured = v20_actual_alpha_from_keel(
                            result.get("object_ids", []), survey_params, translation)
                        if alpha_measured is not None:
                            geometry_row["alpha_measured_deg"] = alpha_measured
                            geometry_row["alpha_error_deg"] = abs(alpha_measured - alpha_value)
                    except Exception:
                        pass
                    self.survey_geometry_results.append(geometry_row)
                    self.survey_geometry_report_area.Text = v20_format_geometry_survey_table(self.survey_geometry_results)
                    if int(self.survey_heatmap_metric.SelectedIndex) == 8:
                        self.on_update_survey_heatmap()

                    # Cho Rhino xử lý message/UI giữa các mẫu, đặc biệt khi tạo 100 tàu.
                    Rhino.RhinoApp.Wait()

            sc.sticky[SURVEY_STICKY_KEY] = all_survey_ids

            self.status_label.Text = (
                u"Đã tạo xong %d mẫu khảo sát" % total_models
            )
            Rhino.RhinoApp.SetCommandPrompt(
                u"Model 112 - hoàn tất khảo sát %d mẫu" % total_models
            )
        except Exception as error:
            # Nếu lỗi giữa chừng vẫn ghi lại các ID đã tạo để nút Xóa có thể dọn sạch.
            sc.sticky[SURVEY_STICKY_KEY] = all_survey_ids
            self.status_label.Text = u"Khảo sát bị dừng do lỗi"
            Rhino.RhinoApp.WriteLine(
                "Model 112 survey error: %s" % str(error)
            )


    def on_clear_survey(
        self,
        sender,
        event
    ):
        clear_sticky_objects(SURVEY_STICKY_KEY)
        self.on_clear_survey_sections()
        sc.doc.Views.Redraw()
        self.survey_model_surfaces = {}
        self.survey_geometry_results = []
        self.survey_geometry_signature = None
        if hasattr(self, "survey_geometry_report_area"):
            self.survey_geometry_report_area.Text = u"Chưa có dữ liệu hình học khảo sát."
        if hasattr(self, "survey_heatmap_area"):
            self.survey_heatmap_area.Content = forms.Label(Text=u"Chưa có dữ liệu Heatmap.")
        self.status_label.Text = u"Đã xóa các mẫu khảo sát"


    def on_reset(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        clear_sticky_objects(PREVIEW_STICKY_KEY)
        self.restore_preview_background()
        clear_sticky_objects(
            LINESPLAN_SOURCE_STICKY_KEY
        )
        clear_sticky_objects(
            LINESPLAN_2D_STICKY_KEY
        )
        sc.sticky[
            LINESPLAN_DATA_STICKY_KEY
        ] = {}
        sc.sticky[
            FINAL_HULL_LINES_STICKY_KEY
        ] = {}
        self.params = HullParameters()
        self.coordinate_extra_columns = []
        self.coordinate_table_data = None
        self.parameter_specs = (
            build_ui_parameter_specs(
                self.params
            )
        )

        for spec in self.parameter_specs:
            if spec.key in self.parameter_controls:
                self.parameter_controls[
                    spec.key
                ]["spec"] = spec

                numeric = self.parameter_controls[
                    spec.key
                ]["numeric"]

                slider = self.parameter_controls[
                    spec.key
                ]["slider"]

                numeric.MinValue = spec.minimum
                numeric.MaxValue = spec.maximum
                numeric.Increment = spec.step
                numeric.DecimalPlaces = spec.decimals

                slider.MinValue = 0
                slider.MaxValue = (
                    self.get_slider_max(
                        spec
                    )
                )

        self.refresh_all_controls()

        if hasattr(
            self,
            "survey_hydro_results"
        ):
            self.survey_hydro_results = []
            self.survey_hydro_signature = None
            self.survey_hydro_cancel_requested = False

            if hasattr(
                self,
                "survey_hydro_report_area"
            ):
                self.survey_hydro_report_area.Text = (
                    u"Chưa có dữ liệu Hydro khảo sát."
                )

            if hasattr(
                self,
                "survey_hydro_summary"
            ):
                self.survey_hydro_summary.Text = (
                    u"Chưa tính thủy tĩnh cho ma trận khảo sát."
                )

        self.update_survey_base_summary()
        self.update_hydro_base_summary()
        self.status_label.Text = (
            u"Đã đặt lại tham số"
        )


    def on_close_clicked(
        self,
        sender,
        event
    ):
        self.Close()


    def on_closed(
        self,
        sender,
        event
    ):
        self.preview_timer.Stop()
        clear_sticky_objects(PREVIEW_STICKY_KEY)
        self.restore_preview_background()
        detach_model112_document_monitor()

        if FORM_STICKY_KEY in sc.sticky:
            del sc.sticky[
                FORM_STICKY_KEY
            ]


DOCUMENT_MONITOR_KEY = "MODEL_112_ACTIVE_DOCUMENT_MONITOR"


def detach_model112_document_monitor():
    callback = sc.sticky.get(DOCUMENT_MONITOR_KEY)
    if callback is not None:
        try:
            Rhino.RhinoDoc.ActiveDocumentChanged -= callback
        except Exception:
            pass
        sc.sticky.pop(DOCUMENT_MONITOR_KEY, None)


def attach_model112_document_monitor():
    """Giữ form độc lập với tài liệu và xóa cache ID khi đổi tài liệu."""
    detach_model112_document_monitor()

    def on_active_document_changed(sender, event):
        doc = Rhino.RhinoDoc.ActiveDoc
        if doc is None:
            return
        sc.doc = doc
        form = sc.sticky.get(FORM_STICKY_KEY)
        if form is None:
            return
        try:
            serial = int(doc.RuntimeSerialNumber)
            if getattr(form, "_active_doc_serial", None) == serial:
                return
            form._active_doc_serial = serial
            form.preview_timer.Stop()
            form._hidden_preview_final_ids = []
            form._hidden_linesplan_source_ids = []
            for key in (
                PREVIEW_STICKY_KEY, FINAL_HULL_OBJECTS_STICKY_KEY,
                FINAL_HULL_LINES_STICKY_KEY, FINAL_HULL_IS_HALF_STICKY_KEY,
                SURVEY_STICKY_KEY,
                LINESPLAN_SOURCE_STICKY_KEY, LINESPLAN_DATA_STICKY_KEY,
                LINESPLAN_2D_STICKY_KEY, HIDDEN_LINESPLAN_SOURCE_STICKY_KEY
            ):
                sc.sticky.pop(key, None)
            form.coordinate_table_data = None
            form.last_hydro_results = []
            form.last_hydro_signature = None
            form.survey_hydro_results = []
            form.survey_hydro_signature = None
            form.survey_geometry_results = []
            form.survey_geometry_signature = None
            form.survey_model_surfaces = {}
            form.survey_hydro_report_area.Text = u"Chưa có dữ liệu Hydro khảo sát."
            form.survey_geometry_report_area.Text = u"Chưa có dữ liệu hình học khảo sát."
            form.survey_heatmap_area.Content = forms.Label(
                Text=u"Chưa có dữ liệu Heatmap."
            )
            form.linesplan_status.Text = (
                u"Đã đổi tài liệu Rhino. Tạo lại nguồn 3D trong tài liệu này."
            )
            form.status_label.Text = u"MODEL 112 đã chuyển sang tài liệu hiện hành"
        except Exception as error:
            Rhino.RhinoApp.WriteLine(
                "Model 112 document switch: %s" % str(error)
            )

    Rhino.RhinoDoc.ActiveDocumentChanged += on_active_document_changed
    sc.sticky[DOCUMENT_MONITOR_KEY] = on_active_document_changed


def show_model_112_interface(
    start_page=None
):
    """Mở giao diện hoặc đưa form đang mở thẳng tới Trang 1-4."""
    if start_page is None:
        start_page = sc.sticky.get(
            START_PAGE_STICKY_KEY,
            0
        )
    try:
        start_page = int(start_page)
    except Exception:
        start_page = 0
    start_page = max(0, min(3, start_page))
    sc.sticky[START_PAGE_STICKY_KEY] = start_page

    existing_form = sc.sticky.get(
        FORM_STICKY_KEY,
        None
    )
    if existing_form is not None:
        try:
            if hasattr(existing_form, "main_pages"):
                existing_form.main_pages.SelectedIndex = start_page
            if not existing_form.Visible:
                existing_form.Show()
            attach_model112_document_monitor()
            existing_form.BringToFront()
            return existing_form
        except Exception:
            try:
                del sc.sticky[
                    FORM_STICKY_KEY
                ]
            except Exception:
                pass

    form = Model112Form()
    try:
        form.main_pages.SelectedIndex = start_page
    except Exception:
        pass
    sc.sticky[FORM_STICKY_KEY] = form
    try:
        # Giao diện đã có màu sắc riêng; Rhino 6/7 không luôn có UseRhinoStyle.
        form._active_doc_serial = int(sc.doc.RuntimeSerialNumber)
        form.Show()
        attach_model112_document_monitor()
    except Exception:
        try:
            del sc.sticky[FORM_STICKY_KEY]
        except Exception:
            pass
        raise
    form.BringToFront()
    return form


def verify_target_rhino_version():
    major = get_rhino_major_version()
    if major != MODEL112_TARGET_RHINO_MAJOR:
        raise Exception(
            u"File này dành cho Rhino 7. Rhino hiện tại: %s. "
            u"Hãy chạy đúng file Model112_Rhino7_RunPythonScript.py trong Rhino 7." %
            str(Rhino.RhinoApp.Version)
        )
    print(
        u"MODEL 112 | %s | Rhino %s" %
        (MODEL112_RUNTIME_NAME, str(Rhino.RhinoApp.Version))
    )


if __name__ == "__main__":
    verify_target_rhino_version()
    show_model_112_interface()
