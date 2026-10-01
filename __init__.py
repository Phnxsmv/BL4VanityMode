import math
import random
import time
from typing import Any
from mods_base import get_pc, SliderOption, Game, build_mod, hook, keybind, GroupedOption
from unrealsdk import find_class, find_object, make_struct # , hooks
from unrealsdk.hooks import Type
assert __import__("mods_base").__version_info__ >= (1, 11), "Please update mods_base"
assert __import__("unrealsdk").__version_info__ >= (1, 3, 0), "Please update unrealsdk"
assert Game.get_current() == Game.BL4, "This mod only supports Borderlands 4"
__version__ = "1.0"
# ---------------------------------------------------------------- tuning

# SLOT = "DefaultSlot"        # character body slot
SLOT = "FullBody"        # character body slot
WYRM_SLOT = "FullBody"      # pet slot, as used by the Manifestation trick asset

# BLEND_IN = 0.25             # entering an activity from normal gameplay
BLEND_IN = 0.5             # entering an activity from normal gameplay
# BLEND_OUT = 0.25            # leaving an activity back to gameplay
BLEND_OUT = 0.5            # leaving an activity back to gameplay
# BLEND_JOIN = 0.08           # between clips inside one activity
BLEND_JOIN = 0.5           # between clips inside one activity

# GAP_MIN, GAP_MAX = 8.0, 20.0    # between activities
GAP_MIN, GAP_MAX = 10.0, 30.0     # between activities
HOLD_MIN, HOLD_MAX = 3.0, 7.0   # how long a group's base idle holds between actions

CAMERA_MODE = "Orbit"
CAMERA_BLEND = 1.0
ORBIT_SPEED = 5.0           # degrees per second
YAW_PER_SEC = ORBIT_SPEED

# the skill's own spawn-out burst, played on the wyrm's head as it disappears
WYRM_OUT_FX = ("/Game/DLC/Harmonica/PlayerCharacters/CorpoHacker/_Shared/Effects/Systems/WYRM/"
               "NS_CorpoHacker_WYRM_Spawn_Out.NS_CorpoHacker_WYRM_Spawn_Out")
WYRM_OUT_SOCKET = "Head"
WYRM_OUT_DELAY = 0.15       # seconds the wyrm stays visible under the burst before hiding
WYRM_REQUIRE_OUT_FX = False # True: only pick the wyrm fidget when the burst is loaded too

EYE_OVERRIDE = {
    "Emissive Color": ("vector", (0.10, 0.50, 0.15)),
    "Emissive Strength Iris": ("scalar", 30.0),
}
HAIR_OVERRIDE = {
    "Color Root": ("vector", (0.30, 0.0, 0.0)),
    "Color Tips": ("vector", (0.75, 0.10, 0.10)),
}
_mine = {}             # (component, slot) -> path of the MID we last wrote
_next_check = 0.0


# ---------------------------------------------------------------- slider options

eye_glow_color_r = SliderOption(
    "Eye Glow Colour Red",
    0.10,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Eye Glow Colour Red",
    description="Eye Glow Colour Red Value.",
)

eye_glow_color_g = SliderOption(
    "Eye Glow Colour Green",
    0.50,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Eye Glow Colour Green",
    description="Eye Glow Colour Green Value.",
)

eye_glow_color_b = SliderOption(
    "Eye Glow Colour Blue",
    0.15,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Eye Glow Colour Blue",
    description="Eye Glow Colour Blue Value.",
)

eye_glow_str = SliderOption(
    "Eye Glow Strength",
    30.0,
    0.0,
    50.0,
    step=1.0,
    is_integer=False,
    display_name="Eye Glow Strength",
    description="Eye Glow Colour Strength.",
)

hair_root_color_r = SliderOption(
    "Hair Root Colour Red",
    0.30,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Hair Root Colour Red",
    description="Hair Root Colour Red Value.",
)

hair_root_color_g = SliderOption(
    "Hair Root Colour Green",
    0.0,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Hair Root Colour Green",
    description="Hair Root Colour Green Value.",
)

hair_root_color_b = SliderOption(
    "Hair Root Colour Blue",
    0.0,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Hair Root Colour Blue",
    description="Hair Root Colour Blue Value.",
)

hair_tips_color_r = SliderOption(
    "Hair Tips Colour Red",
    0.75,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Hair Tips Colour Red",
    description="Hair Tips Colour Red Value.",
)

hair_tips_color_g = SliderOption(
    "Hair Tips Colour Green",
    0.10,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Hair Tips Colour Green",
    description="Hair Tips Colour Green Value.",
)

hair_tips_color_b = SliderOption(
    "Hair Tips Colour Blue",
    0.10,
    0.0,
    1.0,
    step=1.0,
    is_integer=False,
    display_name="Hair Tips Colour Blue",
    description="Hair Tips Colour Blue Value.",
)


# ---------------------------------------------------------------- content

BASE = "/Game/DLC/Harmonica/PlayerCharacters/CorpoHacker/Animation"


def A(rel):
    """Object path for an AnimSequence given its path relative to BASE."""
    return f"{BASE}/{rel}.{rel.rsplit('/', 1)[1]}"


def F(idle, enter=None, exit=None, loops=1, pet=None, weight=1.0):
    """A standalone fidget: optional enter, idle played `loops` times, optional exit.
    `pet` pairs clips for the wyrm, which is shown for the duration."""
    return {"kind": "fidget", "enter": enter, "idle": idle, "exit": exit,
            "loops": loops, "pet": pet, "weight": weight}


def PET(idle, enter=None):
    return {"enter": enter, "idle": idle}


def S(idle, fidgets=(), up=None, down=None):
    """One state of a group. up/down are (target_state, transition_clip)."""
    return {"idle": idle, "fidgets": list(fidgets), "up": up, "down": down}


def G(name, entry, states, actions=(2, 4), weights=None, weight=1.0):
    """A group: settle into `entry`'s idle, take a few actions, walk back down.
    `weights` biases the choice between fidget / up / down at each step."""
    w = {"fidget": 1.0, "up": 1.0, "down": 1.0}
    w.update(weights or {})
    return {"kind": "group", "name": name, "entry": entry, "states": states,
            "actions": actions, "w": w, "weight": weight}


UNARMED = [
    F(A("3rd/Unarmed/AS_UA_Idle_Fidget_01")),
    F(A("3rd/Unarmed/AS_UA_Idle_Fidget_02")),
    F(A("3rd/Unarmed/AS_UA_Idle_Fidget_03")),
    # Contagion, LetItRip, VPN_Function spawn props that are not despawnable
    # F(A("StandIn/AS_SkillFlourish_CorpoHacker_Contagion_Idle"),
    #  enter=A("StandIn/AS_SkillFlourish_CorpoHacker_Contagion_Enter"), loops=2),
    # This is from cut content
    # F(A("StandIn/AS_SkillFlourish_CorpoHacker_LetItRip_Idle"),
    #  enter=A("StandIn/AS_SkillFlourish_CorpoHacker_LetItRip_Enter"), loops=2),
    # F(A("StandIn/AS_SkillFlourish_CorpoHacker_VPN_Function_Idle"),
    #  enter=A("StandIn/AS_SkillFlourish_CorpoHacker_VPN_Function_Enter"), loops=2),
    # paired with the wyrm; its StandIn clips load only once the skills menu has
    # been visited, so until then the wyrm shows with its own gameplay idle
    F(A("StandIn/AS_SkillFlourish_CorpoHacker_Wyrm_Idle"),
      enter=A("StandIn/AS_SkillFlourish_CorpoHacker_Wyrm_Enter"), loops=2,
      pet=PET(A("StandIn/Wyrm/AS_SkillFlourish_CorpoHacker_Wyrm_Idle"),
              enter=A("StandIn/Wyrm/AS_SkillFlourish_CorpoHacker_Wyrm_Enter"))),
]

# StandIn base idle with its fidgets played from it
STANDIN = G("standin", "base", {
    "base": S(A("StandIn/AS_Idle_CorpoHacker"),
              fidgets=[A("StandIn/AS_Fidget_CorpoHacker"),
                       A("StandIn/AS_Fidget_CorpoHacker_v2"),
                       A("StandIn/AS_Fidget_CorpoHacker_v3")]),
}, actions=(2, 4), weight=2.0)

# character-select escalation: unselected -> selected -> confirmed, and back
CHARSELECT = G("charselect", "unselected", {
    "unselected": S(A("CharacterSelect/AS_Unselected_Idle_CorpoHacker"),
                    fidgets=[A("CharacterSelect/AS_NotSelectedFidget_01_CorpoHacker")],
                    up=("selected", A("CharacterSelect/AS_Selected_Enter_CorpoHacker"))),
    "selected":   S(A("CharacterSelect/AS_Selected_Idle_CorpoHacker"),
                    up=("confirmed", A("CharacterSelect/AS_Confirmed_Enter_CorpoHacker")),
                    down=("unselected", A("CharacterSelect/AS_Selected_Exit_CorpoHacker"))),
    "confirmed":  S(A("CharacterSelect/AS_Confirmed_Idle_CorpoHacker"),
                    down=("unselected", A("CharacterSelect/AS_Confirmed_Cancel_CorpoHacker"))),
}, actions=(2, 5), weights={"up": 1.5, "down": 0.7}, weight=2.0)

PISTOL = [
    F(A("3rd/Pistol/_Shared/AS_PS_Idle_Fidget_01")),
    F(A("3rd/Pistol/_Shared/AS_PS_Idle_Fidget_02")),
    F(A("3rd/Pistol/_Shared/AS_PS_Idle_Fidget_03")),
    # Only additive, needs base idle playing
    # F(A("3rd/Pistol/_Shared/AS_ADD_PS_WeaponDown_Inventory_Idle"), loops=300),
]

RIFLE = [
    F(A("3rd/Rifle/_Shared/AS_RH_Idle_Fidget_01")),
    F(A("3rd/Rifle/_Shared/AS_RH_Idle_Fidget_02")),
    F(A("3rd/Rifle/_Shared/AS_RH_Idle_Fidget_03")),
    # Only additive, needs base idle playing
    # F(A("3rd/Rifle/_Shared/AS_ADD_RH_WeaponDown_Inventory_AR_TED_Idle"), loops=300),
    # F(A("3rd/Rifle/_Shared/AS_ADD_RH_WeaponDown_Inventory_Idle"), loops=300),
]

# WeaponType: 0 unarmed, 1 pistol, 2 smg, 3 shotgun, 4 AR, 5 sniper
SETS = {0: UNARMED + [STANDIN, CHARSELECT], 1: PISTOL, 2: RIFLE, 3: RIFLE, 4: RIFLE, 5: RIFLE}

# ---------------------------------------------------------------- state

_enabled = False
_co_enabled = False

_excluded: list = []      # clips dropped for spawning props, reported once per resolve
_resolved: dict = {}      # weapon type -> resolved pool; cleared when the pawn changes
_active_pawn = None       # path of the pawn the state below belongs to
_activity = None          # generator yielding (anim, loops, pet_candidates, blend_in)
_playing_until = 0.0
_next_at = 0.0
_last = None
_camera_pushed = False
_rot_clockwise = False
_wyrm_on = False
_despawn_at = 0.0         # pending wyrm hide, so the burst covers the disappearance
_step_anim = None         # clip currently playing on the body, for notify-state cleanup


run_cmd_class = find_class("KismetSystemLibrary").ClassDefaultObject.ExecuteConsoleCommand


def live(obj: Any) -> bool:
    if obj is None:
        return False
    try:
        if hasattr(obj, "IsValid") and not bool(obj.IsValid()):
            return False
        _ = obj.Name
        return True
    except Exception:
        return False


def get_pc_safe() -> Any | None:
    try:
        pc = get_pc(possibly_loading=True)
    except Exception:
        return None
    return pc if live(pc) else None


def _key(obj):
    try:
        return obj._path_name()
    except Exception:
        return str(obj)


# ---------------------------------------------------------------- resolution

def _find(path):
    """find_object raises when an asset is not loaded; treat that as absent."""
    if not path:
        return None
    try:
        return find_object("AnimSequence", path)
    except Exception:
        return None


def _resolve_fidget(e):
    idle = _find(e["idle"])
    if idle is None:
        return None
    # pet clips stay as paths and are looked up at play time, because their
    # package may only load later in the session
    return dict(e, idle=idle, enter=_find(e["enter"]), exit=_find(e["exit"]))


def _resolve_group(g):
    states = {}
    for name, s in g["states"].items():
        idle = _find(s["idle"])
        if idle is None:
            continue
        fid = [a for a in (_find(p) for p in s["fidgets"]) if a is not None]
        up = down = None
        if s["up"]:
            clip = _find(s["up"][1])
            up = (s["up"][0], clip) if clip else None
        if s["down"]:
            clip = _find(s["down"][1])
            down = (s["down"][0], clip) if clip else None
        states[name] = {"idle": idle, "fidgets": fid, "up": up, "down": down}
    if g["entry"] not in states:
        return None
    for s in states.values():        # drop transitions into states that failed to resolve
        if s["up"] and s["up"][0] not in states:
            s["up"] = None
        if s["down"] and s["down"][0] not in states:
            s["down"] = None
    return dict(g, states=states)


def _resolve(wtype):
    if wtype in _resolved:
        return _resolved[wtype]
    _excluded.clear()
    out = []
    for e in SETS.get(wtype, ()):
        r = _resolve_group(e) if e["kind"] == "group" else _resolve_fidget(e)
        if r is not None:
            out.append(r)
    _resolved[wtype] = out
    if _excluded:
        print(f"vanity: skipping prop-spawning clips {sorted(set(_excluded))}")
    return out


def _available(e):
    """A fidget paired with the wyrm is only eligible once all its wyrm clips are
    loaded; otherwise the wyrm would pop in without its entrance."""
    pet = e.get("pet")
    if not pet:
        return True
    if not all(_find(p) is not None for p in (pet["enter"], pet["idle"]) if p):
        return False
    return (not WYRM_REQUIRE_OUT_FX) or _find_fx() is not None


def _pick(wtype):
    global _last
    pool = [e for e in _resolve(wtype) if _available(e)]
    if not pool:
        return None
    choices = [e for e in pool if e is not _last] or pool
    _last = random.choices(choices, weights=[e["weight"] for e in choices])[0]
    return _last


# ---------------------------------------------------------------- activities

def _duration(anim, loops=1):
    rate = getattr(anim, "RateScale", 1.0) or 1.0
    return (anim.SequenceLength / abs(rate)) * loops


def _hold_loops(anim):
    """Loop count covering a random hold, in whole cycles so the idle never cuts mid-loop."""
    return max(1, math.ceil(random.uniform(HOLD_MIN, HOLD_MAX) / max(_duration(anim), 0.01)))


def _run_fidget(f):
    pet = f.get("pet")
    blend = BLEND_IN
    if f["enter"]:
        # if the pet's enter clip is not loaded, it hovers on its idle meanwhile
        yield (f["enter"], 1, pet and (pet["enter"], pet["idle"]), blend)
        blend = BLEND_JOIN
    yield (f["idle"], f["loops"], pet and (pet["idle"],), blend)
    if f["exit"]:
        yield (f["exit"], 1, pet and (pet["idle"],), BLEND_JOIN)


def _run_group(g):
    states, entry = g["states"], g["entry"]
    st = entry
    yield (states[st]["idle"], _hold_loops(states[st]["idle"]), None, BLEND_IN)
    for _ in range(random.randint(*g["actions"])):
        s = states[st]
        opts = []
        if s["fidgets"]:
            opts.append("fidget")
        if s["up"]:
            opts.append("up")
        if s["down"] and st != entry:
            opts.append("down")
        if not opts:
            break
        kind = random.choices(opts, weights=[g["w"][k] for k in opts])[0]
        if kind == "fidget":
            yield (random.choice(s["fidgets"]), 1, None, BLEND_JOIN)
        else:
            st, clip = s[kind]
            yield (clip, 1, None, BLEND_JOIN)
        yield (states[st]["idle"], _hold_loops(states[st]["idle"]), None, BLEND_JOIN)
    # walk back down to the entry state so the group always ends where it began
    walked = False
    while st != entry and states[st]["down"]:
        st, clip = states[st]["down"]
        yield (clip, 1, None, BLEND_JOIN)
        walked = True
    if walked:
        yield (states[st]["idle"], 1, None, BLEND_JOIN)


# ---------------------------------------------------------------- wyrm

def _set_wyrm(pawn, on):
    global _wyrm_on
    try:
        bd = find_class("GbxBodyData").ClassDefaultObject
        bd.SetBodySwitchState("isSummoningWyrm", "True" if on else "False", pawn, "Body")
    except Exception:
        pass
    _wyrm_on = on


def _wyrm_comp(pawn):
    try:
        bfl = find_class("GbxBodyFunctionLibrary").ClassDefaultObject
        return bfl.GetBodyComponent(pawn, find_class("GbxSkeletalMeshComponent"),
                                    "SummonedWyrm_3P", "None", "None")
    except Exception:
        return None


def _wyrm_anim(pawn):
    comp = _wyrm_comp(pawn)
    try:
        return comp.AnimScriptInstance if comp else None
    except Exception:
        return None


def _find_fx():
    try:
        return find_object("NiagaraSystem", WYRM_OUT_FX)
    except Exception:
        return None


def _spawn_out_fx(pawn):
    """Mirror of the skill's SpawnVFXOut: the burst attached to the wyrm's head."""
    fx = _find_fx()
    comp = _wyrm_comp(pawn)
    if fx is None or comp is None:
        return False
    try:
        gs = find_class("GbxGameplayStatics").ClassDefaultObject
        gs.SpawnEmitterAttached_Generic(
            fx, [], comp, WYRM_OUT_SOCKET,
            make_struct("Vector", X=0.0, Y=0.0, Z=0.0),
            make_struct("Rotator", Pitch=0.0, Yaw=0.0, Roll=0.0),
            make_struct("Vector", X=1.0, Y=1.0, Z=1.0),
            0, True, 0, True, 0, 0)
        return True
    except Exception as ex:
        print("vanity: wyrm spawn-out effect failed:", ex)   # once per despawn, not per frame
        return False


def _play_pet(pawn, candidates, dur, blend):
    anim = next((a for a in (_find(p) for p in candidates) if a is not None), None)
    if anim is None:
        return                      # not loaded: the pet keeps its own gameplay idle
    ai = _wyrm_anim(pawn)
    if ai is None:
        return
    loops = max(1, math.ceil((dur - 0.05) / max(_duration(anim), 0.01)))
    try:
        _play(ai, WYRM_SLOT, anim, loops, blend)
    except Exception:
        pass


def _stop_wyrm(pawn, now):
    """Play the burst and hide the wyrm a moment later under it. Falls back to
    hiding immediately if the effect is not loaded."""
    global _despawn_at
    if not _wyrm_on or _despawn_at:
        return
    ai = _wyrm_anim(pawn)
    if ai is not None:
        try:
            ai.StopSlotAnimation(BLEND_OUT, WYRM_SLOT)
        except Exception:
            pass
    if _spawn_out_fx(pawn):
        _despawn_at = now + WYRM_OUT_DELAY
    else:
        _set_wyrm(pawn, False)


# ---------------------------------------------------------------- prop detection

def _spawns_props(anim):
    """True if the clip carries a notify state that spawns a prop."""
    if anim is None:
        return False
    try:
        for n in anim.Notifies:
            st = getattr(n, "NotifyStateClass", None)
            if st is not None:
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- playback

def _play(ai, slot, anim, loops, blend_in):
    ai.PlaySlotAnimationAsDynamicMontage(anim, slot, blend_in, BLEND_JOIN, 1.0, loops, -1.0, 0.0)


def _schedule(now):
    global _next_at
    _next_at = now + random.uniform(GAP_MIN, GAP_MAX)


def _push_camera(cm, pawn):
    global _camera_pushed, _rot_clockwise, YAW_PER_SEC
    if _camera_pushed:
        return
    _rot_clockwise = not _rot_clockwise          # alternate direction per idle session
    YAW_PER_SEC = ORBIT_SPEED if _rot_clockwise else -ORBIT_SPEED
    run_cmd_class(get_pc_safe(), "gbx.ui.view.stateadd cinematic", get_pc_safe())   # HUD off
    cm.PushActorCameraMode(pawn, CAMERA_MODE, "", CAMERA_BLEND, False)
    _camera_pushed = True


def _pop_camera(cm, pawn):
    global _camera_pushed
    if not _camera_pushed:
        return
    run_cmd_class(get_pc_safe(), "gbx.ui.view.stateremove cinematic", get_pc_safe())  # HUD on
    cm.PopActorCameraMode(pawn, CAMERA_MODE, "", CAMERA_BLEND, False)
    _camera_pushed = False


def _start(entry, body, pawn, cm, now):
    global _activity
    _activity = _run_group(entry) if entry["kind"] == "group" else _run_fidget(entry)
    if entry.get("pet"):
        _set_wyrm(pawn, True)
    _push_camera(cm, pawn)
    _advance(body, pawn, now)


def _advance(body, pawn, now):
    global _playing_until, _step_anim
    _step_anim = None
    try:
        anim, loops, pet, blend = next(_activity)
    except StopIteration:
        _finish(body, pawn, now)
        _schedule(now)
        return
    dur = _duration(anim, loops)
    _playing_until = now + dur - BLEND_JOIN
    _step_anim = anim
    _play(body, SLOT, anim, loops, blend)
    if pet:
        _play_pet(pawn, pet, dur, blend)


def _finish(body, pawn, now):
    """Activity over; the orbit camera stays up for the rest of the idle session."""
    global _activity, _playing_until, _step_anim
    _step_anim = None
    _activity = None
    _playing_until = 0.0
    try:
        body.StopSlotAnimation(BLEND_OUT, SLOT)
    except Exception:
        pass
    _stop_wyrm(pawn, now)


def _abort(body, cm, pawn, now):
    """Player moved, or vanity mode switched off."""
    _finish(body, pawn, now)
    _pop_camera(cm, pawn)


def _forget():
    """The pawn changed (map load, respawn, back from the menu). Everything we
    held belonged to the old one, so drop it without touching those objects."""
    global _activity, _playing_until, _wyrm_on, _camera_pushed, _last, _despawn_at, _step_anim
    if _camera_pushed:
        pc = get_pc_safe()
        if pc is not None:
            try:
                run_cmd_class(pc, "gbx.ui.view.stateremove cinematic", pc)
            except Exception:
                pass
    _activity = None
    _playing_until = 0.0
    _wyrm_on = False
    _despawn_at = 0.0
    _step_anim = None
    _camera_pushed = False
    _last = None
    _resolved.clear()


# ---------------------------------------------------------------- apply eye colour/glow

def param_info(m, name, arr="VectorParameterValues"):
    """The parameter's full identity as the material defines it, from the parents."""
    while m is not None:
        for pv in getattr(m, arr, []) or []:
            if str(pv.ParameterInfo.Name) == name:
                return pv.ParameterInfo
        m = getattr(m, "Parent", None)
    return None


def _apply(mid, OVERRIDE):
    if OVERRIDE == EYE_OVERRIDE:
        for name, (kind, val) in OVERRIDE.items():
            if kind == "vector":
                # mid.SetVectorParameterValue(name, make_struct("LinearColor", R=val[0], G=val[1], B=val[2], A=1.0))
                mid.SetVectorParameterValue(name, make_struct("LinearColor", R=float(eye_glow_color_r.value), G=float(eye_glow_color_g.value), B=float(eye_glow_color_b.value), A=1.0))
            else:
                # mid.SetScalarParameterValue(name, val)
                mid.SetScalarParameterValue(name, float(eye_glow_str.value))
    elif OVERRIDE == HAIR_OVERRIDE:
        for name, (kind, val) in OVERRIDE.items():
            info = param_info(mid.Parent, name)  # the identity the material really uses
            if info is not None:
                # mid.SetVectorParameterValueByInfo(info, make_struct("LinearColor", R=val[0], G=val[1], B=val[2], A=1.0))
                if "root" in str(info).lower():
                    mid.SetVectorParameterValueByInfo(info, make_struct("LinearColor", R=float(hair_root_color_r.value), G=float(hair_root_color_g.value), B=float(hair_root_color_b.value), A=1.0))
                elif "tips" in str(info).lower():
                    mid.SetVectorParameterValueByInfo(info, make_struct("LinearColor", R=float(hair_tips_color_r.value), G=float(hair_tips_color_g.value), B=float(hair_tips_color_b.value), A=1.0))
            else:
                mid.SetVectorParameterValue(name, make_struct("LinearColor", R=val[0], G=val[1], B=val[2], A=1.0))


def color_watchdog_sub(m, c, i, OVERRIDE, key):
    mid = m if "Dynamic" in str(m.Class.Name) else c.CreateDynamicMaterialInstance(i, m, "None")
    _apply(mid, OVERRIDE)
    _mine[key] = mid._path_name()


def color_watchdog(pawn, now):
    global _next_check
    if now < _next_check:
        return
    _next_check = now + 0.5
    for c in pawn.K2_GetComponentsByClass(find_class("MeshComponent")):
        for i in range(c.GetNumMaterials()):
            m = c.GetMaterial(i)
            if m is not None and "eye" in str(m.Name).lower() and "eyeshadow" not in str(m.Name).lower():
                key = (c._path_name(), i)
                if _mine.get(key) == m._path_name():
                    continue  # still ours, nothing undid it
                color_watchdog_sub(m, c, i, EYE_OVERRIDE, key)
            elif m is not None and "hair" in str(m.Name).lower():
                key = (c._path_name(), i)
                if _mine.get(key) == m._path_name():
                    continue  # still ours, nothing undid it
                color_watchdog_sub(m, c, i, HAIR_OVERRIDE, key)


# ---------------------------------------------------------------- main loop

@hook(
    "/Game/PlayerCharacters/_Shared/Animation/BPAnim_Player_1st.BPAnim_Player_1st_C"
    ":BlueprintUpdateAnimation",
    Type.PRE,
)
def vanity_tick(obj, args, ret, func) -> None:
    global _active_pawn, _despawn_at

    pc = get_pc_safe()
    if pc is None:
        return
    pawn = pc.Pawn
    if pawn is None:
        return
    body = pawn.Mesh.AnimScriptInstance
    cm = pc.PlayerCameraManager
    if body is None or cm is None:
        return

    key = _key(pawn)
    if _active_pawn is not None and key != _active_pawn:
        _forget()
    _active_pawn = key

    now = time.monotonic()

    # apply eye color/glow
    if _co_enabled:
        color_watchdog(pawn, now)

    busy = _activity is not None

    if _despawn_at and now >= _despawn_at:
        _set_wyrm(pawn, False)
        _despawn_at = 0.0
    wyrm_live = _wyrm_on and not _despawn_at

    if not _enabled:
        if busy or _camera_pushed or wyrm_live:
            _abort(body, cm, pawn, now)
        return

    if not pc.IsIdle():
        if busy or _camera_pushed or wyrm_live:
            _abort(body, cm, pawn, now)
        _schedule(now)
        return

    # Do not trigger vanity cam in menus
    if obj.bInMenu:
        return
    elif body.bInMenu:
        return

    # Do not trigger vanity cam while driving
    if obj.bIsDriving:
        return

    # auto 1p weapon lower on idle
    obj.bWeaponLowered = True
    # auto 3p weapon lower on idle
    body.bWeaponLowered = True

    # keep the orbit turning
    if _camera_pushed and YAW_PER_SEC:
        delta = make_struct("Rotator", Pitch=0.0, Yaw=YAW_PER_SEC * args.DeltaTimeX, Roll=0.0)
        cm.ApplyActorCameraRotation(pawn, delta)

    if busy:
        if now >= _playing_until:
            _advance(body, pawn, now)
        return

    if now < _next_at:
        return

    try:
        wtype = int(getattr(body, "WeaponType", 0))
    except Exception:
        wtype = 0
    entry = _pick(wtype)
    if entry is None:
        _schedule(now)
        return
    _start(entry, body, pawn, cm, now)

# hooks.remove_hook("/Game/PlayerCharacters/_Shared/Animation/BPAnim_Player_1st.BPAnim_Player_1st_C:BlueprintUpdateAnimation", Type.PRE, "vanity_tick")
# hooks.add_hook("/Game/PlayerCharacters/_Shared/Animation/BPAnim_Player_1st.BPAnim_Player_1st_C:BlueprintUpdateAnimation", Type.PRE, "vanity_tick", vanity_tick)

@keybind("Vanity Mode Toggle", "N", display_name="Vanity Mode Toggle")
def vm_toggle() -> None:
    global _enabled
    _enabled = not _enabled
    if _enabled:
        _schedule(time.monotonic())
        print("Vanity Mode active!")
    else:
        print("Vanity Mode inactive!")

@keybind("Color Override Toggle", "L", display_name="Color Override Toggle")
def co_toggle() -> None:
    global _co_enabled
    _co_enabled = not _co_enabled
    if _co_enabled:
        print("Color Override active!")
    else:
        print("Color Override inactive!")

def on_disable() -> None:
    global _enabled, _co_enabled
    _enabled = False
    _co_enabled = False
    vanity_tick.disable()
    print("Vanity Mode inactive!")
    print("Color Override inactive!")

def on_enable() -> None:
    global _enabled, _co_enabled
    _enabled = True
    _co_enabled = True
    _schedule(time.monotonic())
    vanity_tick.enable()
    print("Vanity Mode active!")
    print("Color Override active!")

# vm_toggle()
# co_toggle()

options = [
    GroupedOption(
        "ColorOverride",
        [
            eye_glow_color_r,
            eye_glow_color_g,
            eye_glow_color_b,
            eye_glow_str,
            hair_root_color_r,
            hair_root_color_g,
            hair_root_color_b,
            hair_tips_color_r,
            hair_tips_color_g,
            hair_tips_color_b,
        ],
    ),
]

mod = build_mod(
    name="BL4 Vanity Mode Toggle",
    author="Phnx",
    version=__version__,
    description=(
        "BL4 vanity mode toggle for Loveless."
    ),
    supported_games=Game.BL4,
    keybinds=[
        vm_toggle, co_toggle
    ],
    options=options,
    on_enable=on_enable,
    on_disable=on_disable,
)