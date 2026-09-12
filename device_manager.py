#!/usr/bin/env python3
"""
Device Manager & Compatibility Profile Resolver for OnePlus Buds / HeyMelody
Provides multi-device support across categories:
  - T1: Active Noise Cancellation (ANC) True Wireless Stereo (TWS)
  - T2: Standard True Wireless Stereo (Non-ANC / Entry-level)
  - O1: Open-Ear Clip Earphones
  - N:  Neckband Earphones (Single Battery, Quick Switch, Magnetic Controls)

Indexes all 82 models from live_device_compatibility_catalog.json with offline
deterministic fallback, fuzzy advertisement name matching, and category rules.
"""

import os
import sys
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

CATALOG_FILENAME = "live_device_compatibility_catalog.json"

_this_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()

# Candidate search paths for the catalog JSON
CATALOG_SEARCH_PATHS = [
    os.path.join(_this_dir, CATALOG_FILENAME),
    os.path.join(_this_dir, "Resources", CATALOG_FILENAME),
    os.path.join(os.path.dirname(_this_dir), "Resources", CATALOG_FILENAME),
    os.path.expanduser(f"~/{CATALOG_FILENAME}"),
    os.path.expanduser(f"~/HeyMelody_unpacked/{CATALOG_FILENAME}"),
    f"/Applications/OnePlus Buds.app/Contents/Resources/{CATALOG_FILENAME}",
    f"/Applications/OnePlus Buds Settings.app/Contents/Resources/{CATALOG_FILENAME}",
    f"/Applications/HeyMelody.app/Contents/Resources/{CATALOG_FILENAME}",
    f"/Applications/HeyMelody Menu Bar.app/Contents/Resources/{CATALOG_FILENAME}",
]

# Standard Service and Characteristic UUIDs across generations
GATT_UUID_V1 = "0000079A-D102-11E1-9B23-00025B00A5A5"  # Newer buds (Buds 3, Buds Pro 3, Enco X2/X3)
GATT_UUID_V2 = "00001107-D102-11E1-9B23-00025B00A5A5"  # Older buds & neckbands (Buds Pro 1, Bullets Z2/Z3)
FAST_PAIR_UUID = "FE2C123A-8366-4814-8EB0-01DE32100BEA"

TX_CHAR_V1 = "0100079A-D102-11E1-9B23-00025B00A5A5"
RX_CHAR_V1 = "0200079A-D102-11E1-9B23-00025B00A5A5"

TX_CHAR_LEGACY = "db764ac8-4b08-7f25-aafe-59d03c27bae3"
RX_CHAR_LEGACY = "db764ac8-4b08-7f25-aafe-59d03c27bae4"


@dataclass
class DeviceProfile:
    product_id: str
    name: str
    brand: str
    device_type: str  # 'T1', 'T2', 'O1', 'N'
    uuid: str
    has_anc: bool
    anc_modes: List[str]
    has_spatial: bool
    has_game_mode: bool
    has_in_ear: bool
    has_dual_connect: bool
    has_bass_boost: bool
    has_vocal_enhance: bool
    has_case: bool
    is_neckband: bool
    eq_presets: List[str]
    cover_image_url: Optional[str] = None
    latest_firmware_version: Optional[str] = None
    firmware_download_url: Optional[str] = None
    supported_features: Dict[str, Any] = field(default_factory=dict)

    @property
    def category_title(self) -> str:
        if self.device_type == "T1":
            return "Active Noise Cancellation Earbuds"
        elif self.device_type == "T2":
            return "True Wireless Stereo Earbuds"
        elif self.device_type == "O1":
            return "Open-Ear Clip Earbuds"
        elif self.device_type == "N":
            return "Wireless Neckband Headset"
        return "Wireless Earbuds"

    @property
    def battery_layout(self) -> str:
        """Returns 'three_gauge' (Left/Right/Case) or 'single_gauge' (Unified)."""
        return "single_gauge" if self.is_neckband else "three_gauge"

    @property
    def has_spatial_audio(self) -> bool:
        return self.has_spatial

    @property
    def has_basswave(self) -> bool:
        return self.has_bass_boost

    @property
    def has_dual_device(self) -> bool:
        return self.has_dual_connect

    @property
    def has_vocal_enhancement(self) -> bool:
        return self.has_vocal_enhance

    @property
    def is_open_ear(self) -> bool:
        return self.device_type == "O1"

    @property
    def model_code(self) -> str:
        return self.product_id


# Default Profile for OnePlus Buds 3 (T1 flagship baseline)
DEFAULT_PROFILE = DeviceProfile(
    product_id="063C14",
    name="OnePlus Buds 3",
    brand="OnePlus",
    device_type="T1",
    uuid=GATT_UUID_V1,
    has_anc=True,
    anc_modes=["High", "Moderate", "Low", "Auto"],
    has_spatial=True,
    has_game_mode=True,
    has_in_ear=True,
    has_dual_connect=True,
    has_bass_boost=True,
    has_vocal_enhance=False,
    has_case=True,
    is_neckband=False,
    eq_presets=["Balanced", "Bass", "Clear", "Bold"],
    cover_image_url="https://iot-earbuds-in.heytapimg.com/earbuds-in/test-report-20231221151624838-1_all_111_0.png",
    latest_firmware_version="111.111.101",
    firmware_download_url=None,
    supported_features={"noiseReductionMode": True, "spatialAudio": 1, "equalizer": 4, "fitDetection": 1, "multiDevicesConnect": 1, "gameMode": 1}
)


class DeviceCatalog:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DeviceCatalog, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.profiles_by_id: Dict[str, DeviceProfile] = {}
        self.profiles_by_name: Dict[str, DeviceProfile] = {}
        self.all_profiles: List[DeviceProfile] = []
        self._load_catalog()

    def _find_catalog_path(self) -> Optional[str]:
        for p in CATALOG_SEARCH_PATHS:
            if os.path.isfile(p):
                return p
        return None

    def _load_catalog(self):
        cat_path = self._find_catalog_path()
        catalog_data = []

        if cat_path:
            try:
                with open(cat_path, "r", encoding="utf-8") as f:
                    catalog_data = json.load(f)
            except Exception as e:
                print(f"[DeviceCatalog] Warning: Failed to load catalog from {cat_path}: {e}")

        if not catalog_data:
            # Add default fallback
            self.all_profiles = [DEFAULT_PROFILE]
            self.profiles_by_id[DEFAULT_PROFILE.product_id.upper()] = DEFAULT_PROFILE
            self.profiles_by_name[DEFAULT_PROFILE.name.lower()] = DEFAULT_PROFILE
            return

        for item in catalog_data:
            try:
                pid = str(item.get("productId", "")).strip().upper()
                name = str(item.get("name", "")).strip()
                if not name:
                    continue

                brand = str(item.get("brand", "OnePlus")).capitalize()
                raw_type = str(item.get("type", "T1")).strip().upper()
                uuid = str(item.get("uuid", GATT_UUID_V1)).strip().upper()
                cover_img = item.get("liveCoverImageUrl")

                # Firmware info
                fw_info = item.get("latestFirmware")
                fw_ver = None
                fw_url = None
                if isinstance(fw_info, dict):
                    fw_ver = fw_info.get("versionName")
                    fw_url = fw_info.get("downloadUrl")
                elif isinstance(fw_info, list) and fw_info:
                    fw_ver = fw_info[0].get("versionName") if isinstance(fw_info[0], dict) else None
                    fw_url = fw_info[0].get("downloadUrl") if isinstance(fw_info[0], dict) else None

                raw_feats = item.get("supportedFeatures", {})
                if isinstance(raw_feats, str):
                    try:
                        raw_feats = json.loads(raw_feats)
                    except Exception:
                        raw_feats = {}

                # Feature Flags
                has_nrm = "noiseReductionMode" in raw_feats
                has_nr = "noiseReduction" in raw_feats or "anc" in raw_feats
                has_anc = bool(has_nrm or has_nr)

                # ANC Modes
                anc_modes = []
                if has_anc:
                    nrm_val = raw_feats.get("noiseReductionMode")
                    if isinstance(nrm_val, list) and len(nrm_val) > 0:
                        # Multi-level ANC (Depth, Moderate, Mild, Smart/Auto)
                        has_children = any(bool(m.get("childrenMode")) for m in nrm_val if isinstance(m, dict))
                        if has_children or len(nrm_val) >= 3:
                            anc_modes = ["High", "Moderate", "Low", "Auto"]
                        else:
                            anc_modes = ["Auto"]
                    else:
                        anc_modes = ["High", "Moderate", "Low", "Auto"]

                has_spatial = bool(raw_feats.get("spatialTypes") or raw_feats.get("spatialAudio") or raw_feats.get("spatialDescriptionType") or raw_feats.get("soundEffect"))
                has_game = bool(raw_feats.get("gameMode") or raw_feats.get("lowLatency") or raw_feats.get("game_mode"))
                has_in_ear = bool(raw_feats.get("wearDetection") or raw_feats.get("fitDetection") or raw_feats.get("inEarDetection") or raw_feats.get("earScan"))
                has_dual = bool(raw_feats.get("multiDevicesConnect") or raw_feats.get("dualConnect"))
                has_bass = bool(raw_feats.get("bassEngineSupport") or raw_feats.get("bassWave") or raw_feats.get("bass_boost"))
                has_vocal = bool(raw_feats.get("vocalEnhancement") or raw_feats.get("voiceEnhance") or raw_type == "O1")

                # Device category rules
                is_neckband = (raw_type == "N") or ("bullets" in name.lower() and "buds" not in name.lower())
                has_case = not is_neckband

                # EQ Presets
                eq_val = raw_feats.get("equalizer", 4)
                if eq_val == 4 or "customEqualizer" in raw_feats:
                    eq_presets = ["Balanced", "Bass", "Clear", "Bold"]
                elif eq_val == 3:
                    eq_presets = ["Balanced", "Bass", "Clear"]
                elif eq_val == 2:
                    eq_presets = ["Balanced", "Bass"]
                else:
                    eq_presets = ["Balanced", "Bass", "Clear", "Bold"]

                profile = DeviceProfile(
                    product_id=pid,
                    name=name,
                    brand=brand,
                    device_type=raw_type,
                    uuid=uuid,
                    has_anc=has_anc,
                    anc_modes=anc_modes,
                    has_spatial=has_spatial,
                    has_game_mode=has_game,
                    has_in_ear=has_in_ear,
                    has_dual_connect=has_dual,
                    has_bass_boost=has_bass,
                    has_vocal_enhance=has_vocal,
                    has_case=has_case,
                    is_neckband=is_neckband,
                    eq_presets=eq_presets,
                    cover_image_url=cover_img,
                    latest_firmware_version=fw_ver,
                    firmware_download_url=fw_url,
                    supported_features=raw_feats
                )

                self.all_profiles.append(profile)
                if pid:
                    self.profiles_by_id[pid] = profile
                self.profiles_by_name[name.lower()] = profile

            except Exception as e:
                print(f"[DeviceCatalog] Error parsing item {item.get('name')}: {e}")

        # Sort profiles by name length descending for longest-match substring matching
        self.all_profiles.sort(key=lambda p: len(p.name), reverse=True)

    def get_profile_by_id(self, product_id: str) -> Optional[DeviceProfile]:
        if not product_id:
            return None
        return self.profiles_by_id.get(product_id.strip().upper())

    def get_profile_by_name(self, name: str) -> Optional[DeviceProfile]:
        if not name:
            return None
        raw_name = name.strip()
        clean_name = raw_name.lower()
        clean_no_poss = re.sub(r"[\x27\u2019]s\b", "", clean_name)
        clean_no_suffix = re.sub(r"\(.*?\)|\[.*?\]|- find my|find my|le-", "", clean_no_poss).strip()

        # 1. Reject non-supported foreign audio brands immediately
        foreign_brands = {
            "galaxy", "samsung", "apple", "airpods", "beats", "google", "pixel",
            "sony", "bose", "jbl", "huawei", "xiaomi", "redmi", "anker",
            "soundcore", "sennheiser", "fingers", "boat", "noise", "boult", "marshall"
        }
        if any(fb in clean_name for fb in foreign_brands):
            return None

        # 2. Exact match
        if clean_name in self.profiles_by_name:
            return self.profiles_by_name[clean_name]
        if clean_no_suffix in self.profiles_by_name:
            return self.profiles_by_name[clean_no_suffix]

        # Detect brand in input if explicitly present
        input_brand = None
        for b in ["oneplus", "oppo", "realme"]:
            if b in clean_name:
                input_brand = b
                break

        # 2. Substring match (longest catalog name that is a substring of the advertisement name)
        # Handles user custom names like "Digvijay's OnePlus Buds Pro 3" or "OnePlus Buds 3 - Find My"
        for p in self.all_profiles:
            if input_brand and p.brand.lower() != input_brand:
                continue
            p_name_lower = p.name.lower()
            if p_name_lower in clean_name or p_name_lower in clean_no_suffix:
                return p

        # 3. Clean token-based matching (e.g. matching "Digvijay's Buds 3" to "OnePlus Buds 3", "Nord Buds 2" to "OnePlus Nord Buds 2")
        input_tokens = set(re.findall(r"[a-z0-9]+", clean_no_suffix))
        best_p = None
        best_score = -1

        for p in self.all_profiles:
            if input_brand and p.brand.lower() != input_brand:
                continue
            p_toks = set(re.findall(r"[a-z0-9]+", p.name.lower()))
            p_toks_nobrand = {t for t in p_toks if t not in ["oneplus", "oppo", "realme"]}

            if p_toks_nobrand and p_toks_nobrand.issubset(input_tokens):
                # Ensure qualifier tokens (e.g. pro, 2r, anc, lite, ace) align
                qualifiers = {"pro", "r", "2r", "3r", "anc", "plus", "max", "lite", "ce", "v", "3v", "x", "x2", "x3", "ace"}
                p_qualifiers = p_toks & qualifiers
                in_qualifiers = input_tokens & qualifiers
                if p_qualifiers == in_qualifiers:
                    score = len(p_toks_nobrand) * 10 - len(input_tokens - p_toks_nobrand)
                    if score > best_score:
                        best_score = score
                        best_p = p

        if best_p:
            return best_p

        # 4. Keyword heuristics if not directly matched
        if "bullets" in clean_name or "neckband" in clean_name:
            if "anc" in clean_name or "z2" in clean_name:
                return self.get_profile_by_name("OnePlus BulletsWireless Z2 ANC") or self.all_profiles[0]
            return self.get_profile_by_name("OnePlus Bullets Wireless Z3") or self.all_profiles[0]

        if "clip" in clean_name:
            return self.get_profile_by_name("OPPO Enco Clip") or self.all_profiles[0]

        if "nord" in clean_name:
            if "2r" in clean_name or "3r" in clean_name:
                return self.get_profile_by_name("OnePlus Nord Buds 2r") or self.all_profiles[0]
            if "pro" in clean_name:
                return self.get_profile_by_name("OnePlus Nord Buds 3 Pro") or self.all_profiles[0]
            return self.get_profile_by_name("OnePlus Nord Buds 2") or self.all_profiles[0]

        return None

    def get_profile(self, name_or_id: Optional[str] = None) -> DeviceProfile:
        """
        Universal resolver: Given an advertisement name, model name, or 6-char Product ID,
        returns the best matching DeviceProfile, or the robust OnePlus Buds 3 default.
        """
        if not name_or_id:
            return DEFAULT_PROFILE

        val = name_or_id.strip()

        # Try Product ID lookup (if 6 alphanumeric hex characters)
        if len(val) == 6 and re.match(r"^[0-9A-Fa-f]{6}$", val):
            prof = self.get_profile_by_id(val)
            if prof:
                return prof

        # Try Name lookup
        prof = self.get_profile_by_name(val)
        if prof:
            return prof

        # Fallback to OnePlus Buds 3
        return DEFAULT_PROFILE

    def match_supported_device(self, name_or_id: Optional[str]) -> Optional[DeviceProfile]:
        """
        Extensible matcher: returns the DeviceProfile if the device matches any
        supported OnePlus, OPPO, or Realme earbud/headphone in the catalog, or None.
        Does NOT fall back to DEFAULT_PROFILE for non-matching devices (e.g. keyboards,
        mice, Apple AirPods, Sony headphones, phones).
        """
        if not name_or_id:
            return None

        val = name_or_id.strip()

        # 1. Product ID lookup
        if len(val) == 6 and re.match(r"^[0-9A-Fa-f]{6}$", val):
            prof = self.get_profile_by_id(val)
            if prof:
                return prof

        # 2. Exact or substring match in catalog
        prof = self.get_profile_by_name(val)
        if prof:
            return prof

        # 3. Known brand + audio model heuristics for newly released / custom named buds
        clean = val.lower()
        has_brand = any(b in clean for b in ["oneplus", "oppo", "realme"])
        has_audio = any(k in clean for k in ["buds", "enco", "bullets", "headset", "wireless", "earbuds", "earphones"])
        if has_brand and has_audio:
            detected_brand = "OnePlus"
            for b in ["oneplus", "oppo", "realme"]:
                if b in clean:
                    detected_brand = "OPPO" if b == "oppo" else b.capitalize()
                    break
            is_neck = "bullets" in clean or "neckband" in clean or "buds wireless" in clean
            has_anc_guess = any(x in clean for x in ["pro", "anc", "plus", "max"])
            return DeviceProfile(
                product_id="DYNAMIC",
                name=val,
                brand=detected_brand,
                device_type="N" if is_neck else ("T1" if has_anc_guess else "T2"),
                uuid=GATT_UUID_V1,
                has_anc=has_anc_guess,
                anc_modes=["High", "Moderate", "Low", "Auto"] if has_anc_guess else [],
                has_spatial=True,
                has_game_mode=True,
                has_in_ear=True,
                has_dual_connect=True,
                has_bass_boost=True,
                has_vocal_enhance=False,
                has_case=not is_neck,
                is_neckband=is_neck,
                eq_presets=["Balanced", "Bass", "Clear", "Bold"],
            )

        return None

    def is_supported_device(self, name_or_id: Optional[str]) -> bool:
        """Returns True if the device matches any supported earbud or headphone."""
        return self.match_supported_device(name_or_id) is not None

    def list_all(self) -> List[DeviceProfile]:
        return list(self.all_profiles)

    def list_by_type(self, device_type: str) -> List[DeviceProfile]:
        return [p for p in self.all_profiles if p.device_type == device_type.upper()]


# Global singleton instance
catalog = DeviceCatalog()
CATALOG_PROFILES = catalog.all_profiles
CATALOG_DATA = catalog.all_profiles


def get_device_profile(name_or_id: Optional[str] = None) -> DeviceProfile:
    """Convenience helper to retrieve profile from global catalog."""
    return catalog.get_profile(name_or_id)


def match_supported_device(name_or_id: Optional[str] = None) -> Optional[DeviceProfile]:
    """Convenience helper to check and match a device against the supported catalog."""
    return catalog.match_supported_device(name_or_id)


def is_supported_device(name_or_id: Optional[str] = None) -> bool:
    """Convenience helper to check if a device is in the supported catalog."""
    return catalog.is_supported_device(name_or_id)


if __name__ == "__main__":
    print(f"Loaded {len(catalog.all_profiles)} device profiles.")
    
    test_queries = [
        "OnePlus Buds 3",
        "Digvijay's OnePlus Buds Pro 3",
        "OPPO Enco Air4（新声版）",
        "OPPO Enco Clip2",
        "OnePlus Bullets Wireless Z3",
        "OnePlus BulletsWireless Z2 ANC",
        "063C14",
        "051014",
        "06E010",
        "Unknown Custom Earbuds",
    ]

    print("\n--- Resolver Verification ---")
    for q in test_queries:
        p = get_device_profile(q)
        print(f"Query: '{q}' -> {p.name} [{p.device_type}] (Brand: {p.brand}, ANC: {p.has_anc}, Battery: {p.battery_layout}, Spatial: {p.has_spatial})")
