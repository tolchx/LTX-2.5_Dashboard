"""Bloques de camara para LTX-2.5 — una sola instruccion por clip, lenta, EN POSITIVO.

Por que existe este modulo: el bloque viejo (STATIC_HEAD / STATIC_BLOCK) pedia la
camara quieta con una lista larga de NEGACIONES ("no zoom, no pan, no dolly...") y
el modelo igual acerco el encuadre en todos los clips (medido: +2 % a +6 % de escala
entre el primer y el ultimo frame, con deriva lateral de 60-77 px a 480 px de ancho).
Las negaciones pesan poco en LTX; una orden positiva con direccion, magnitud y
velocidad constantes se sigue mucho mejor. Y como todos los clips salian iguales,
ahora cada item rota por una lista de movimientos distintos.

Uso:
    from camara import CAM_MOVES, ORDEN, aplicar, limpiar
    it["prompt"] = aplicar(base_sin_bloques, "paneo-der")
"""

# Cabezas y colas de versiones anteriores, para poder limpiar un prompt ya marcado.
_VIEJO_STATIC_HEAD = (
    "Static locked-off camera, fixed framing: the shot holds the same distance, "
    "scale and framing from the first frame to the last, no zoom in or out, while "
    "the scene keeps its slow motion inside the frame. "
)
_MARCAS_COLA = ("\n\nSTATIC CAMERA, FIXED FRAME.", "\n\nSTATIC SHOT.", "\n\nCAMERA MOVE",
                "\n\nCAMERA:")

# Cierre comun: lo ultimo que lee el modelo, y lo que mas pesa.
_CIERRE = (
    "One single camera move for the whole clip, at a constant slow speed from the "
    "first frame to the last: no acceleration, no ease-in, no ease-out, no snap, no "
    "second move, no handheld shake, no roll, no focus pull, no lens change. "
    "Perspective stays photographic and coherent: no warping, no morphing, no bending "
    "of straight lines, no flicker, no exposure jump. "
    "No cuts, no scene change, no fades, no speed ramp, no text, no lettering, "
    "no logo, no watermark, no interface. "
    "The scene keeps living at the same time — mist drifting, candles flickering, "
    "particles and pollen floating, cloth and macrame swinging very slowly, water "
    "rippling, smoke curling through the beams — but the light direction, palette and "
    "exposure stay constant. "
    "Photoreal cinematic, shallow depth of field, fine 35mm film grain."
)

# Orden de rotacion. Se asigna por posicion en la cola, asi dos clips seguidos nunca
# repiten movimiento y las variantes A y B de una misma toma tampoco.
ORDEN = ["loop", "paneo-der", "travelling-izq", "tilt-arriba", "paneo-izq",
         "estatica", "travelling-der", "descenso", "arco-der",
         "paneo-der-lento", "tilt-abajo", "travelling-izq-lento", "arco-izq"]

CAM_MOVES = {
    # ---------------------------------------------------------------- paneos
    "paneo-der": {
        "etiqueta": "paneo lento a la derecha",
        "head": ("Very slow, smooth pan to the RIGHT. The camera yaws right at a constant gentle "
                 "speed, a fixed focal length, no zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SLOW PAN TO THE RIGHT. The camera sits on a fluid head and yaws "
                 "steadily to the RIGHT for the entire clip, about 15 degrees of rotation from the "
                 "first frame to the last, the speed a person would use to follow a bird walking: "
                 "perfectly even, same speed in every frame. The frame slides right and new detail "
                 "keeps entering from the right edge while detail leaves at the left edge — this is "
                 "a rotation of the camera body, the lens keeps exactly the same focal length, "
                 "distance and focus. The horizon stays perfectly level, no roll, no tilt."),
    },
    "paneo-izq": {
        "etiqueta": "paneo lento a la izquierda",
        "head": ("Very slow, smooth pan to the LEFT. The camera yaws left at a constant gentle "
                 "speed, a fixed focal length, no zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SLOW PAN TO THE LEFT. The camera sits on a fluid head and yaws "
                 "steadily to the LEFT for the entire clip, about 15 degrees of rotation from the "
                 "first frame to the last, the speed a person would use to follow a bird walking: "
                 "perfectly even, same speed in every frame. The frame slides left and new detail "
                 "keeps entering from the left edge while detail leaves at the right edge — this is "
                 "a rotation of the camera body, the lens keeps exactly the same focal length, "
                 "distance and focus. The horizon stays perfectly level, no roll, no tilt."),
    },
    "paneo-der-lento": {
        "etiqueta": "paneo mínimo a la derecha",
        "head": ("Almost static camera with a whisper of a pan to the RIGHT, constant focal length, "
                 "no zoom in or out."),
        "tail": ("CAMERA MOVE — NEARLY STILL, A HINT OF PAN RIGHT. The frame is held almost locked "
                 "off and drifts to the RIGHT by only about 8 degrees over the whole clip, a barely "
                 "perceptible, perfectly even slide, as if the tripod head were being breathed on: "
                 "same speed in every frame, no zoom in, no zoom out, no push in, no pull back, "
                 "constant focal length and focus, horizon perfectly level."),
    },
    # ----------------------------------------------------------- travellings
    "travelling-der": {
        "etiqueta": "travelling lateral a la derecha",
        "head": ("Very slow lateral tracking move to the RIGHT: the camera body slides sideways, "
                 "parallel to the scene, constant distance, constant focal length, no zoom."),
        "tail": ("CAMERA MOVE — ONE SLOW LATERAL TRAVELLING TO THE RIGHT. The whole camera body "
                 "slides sideways to the RIGHT on a smooth rail, staying parallel to the subject, "
                 "covering a short distance — roughly a quarter of a metre, a slow walking pace — "
                 "for the entire clip at an even speed. Because the camera translates and does not "
                 "rotate, the parallax between foreground and background shifts very slowly and "
                 "reveals depth; the subject stays the same size and the same distance away. The "
                 "lens does not rotate, does not zoom in, does not zoom out, does not change focal "
                 "length, and the horizon stays level."),
    },
    "travelling-izq": {
        "etiqueta": "travelling lateral a la izquierda",
        "head": ("Very slow lateral tracking move to the LEFT: the camera body slides sideways, "
                 "parallel to the scene, constant distance, constant focal length, no zoom."),
        "tail": ("CAMERA MOVE — ONE SLOW LATERAL TRAVELLING TO THE LEFT. The whole camera body "
                 "slides sideways to the LEFT on a smooth rail, staying parallel to the subject, "
                 "covering a short distance — roughly a quarter of a metre, a slow walking pace — "
                 "for the entire clip at an even speed. Because the camera translates and does not "
                 "rotate, the parallax between foreground and background shifts very slowly and "
                 "reveals depth; the subject stays the same size and the same distance away. The "
                 "lens does not rotate, does not zoom in, does not zoom out, does not change focal "
                 "length, and the horizon stays level."),
    },
    "travelling-izq-lento": {
        "etiqueta": "travelling mínimo a la izquierda",
        "head": ("Almost static camera with a whisper of lateral movement to the LEFT, constant "
                 "focal length, no zoom in or out."),
        "tail": ("CAMERA MOVE — NEARLY STILL, A HINT OF LATERAL LEFT. The camera is held almost "
                 "locked off and slides sideways to the LEFT by only a few centimetres over the "
                 "whole clip, an even, barely perceptible drift that only shows in the parallax of "
                 "the nearest leaves and lanterns. No rotation, no zoom in, no zoom out, no push in, "
                 "no pull back, constant focal length and focus."),
    },
    # --------------------------------------------------------------- tilt
    "tilt-arriba": {
        "etiqueta": "tilt lento hacia arriba",
        "head": ("Very slow tilt upward: the camera lens rises gently, constant focal length, no "
                 "zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SLOW TILT UP. The camera head tilts slowly UPWARD for the whole "
                 "clip, about 12 degrees of vertical rotation, the speed of a person lifting their "
                 "eyes: perfectly even, same speed in every frame. The bottom of the shot leaves the "
                 "frame and new detail enters from the top, revealing the upper part of the "
                 "structure and the canopy above. It is a pure vertical rotation of the camera: the "
                 "lens keeps the same focal length and focus, no zoom in, no zoom out, no push in, "
                 "no pull back, verticals stay vertical, no roll, no lateral drift."),
    },
    "tilt-abajo": {
        "etiqueta": "tilt lento hacia abajo",
        "head": ("Very slow tilt downward: the camera lens lowers gently, constant focal length, no "
                 "zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SLOW TILT DOWN. The camera head tilts slowly DOWNWARD for the "
                 "whole clip, about 12 degrees of vertical rotation, the speed of a person lowering "
                 "their eyes: perfectly even, same speed in every frame. The top of the shot leaves "
                 "the frame and new detail enters from the bottom — the base of the structure, the "
                 "objects on the floor, the reflections. It is a pure vertical rotation of the "
                 "camera: the lens keeps the same focal length and focus, no zoom in, no zoom out, "
                 "no push in, no pull back, verticals stay vertical, no roll, no lateral drift."),
    },
    # ------------------------------------------------------ grúa / pedestal
    "descenso": {
        "etiqueta": "descenso lento de grúa",
        "head": ("Very slow camera descent: the camera body lowers gently on a pedestal, keeping its "
                 "angle, constant focal length, no zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SLOW PEDESTAL DOWN. The whole camera body descends slowly on a "
                 "crane or pedestal for the entire clip, about twenty centimetres, at an even speed, "
                 "while the lens keeps exactly the same angle, focal length and focus: the framing "
                 "does not rotate and does not zoom, the viewpoint simply glides downward, so the "
                 "closer foreground rises in the frame and the subject is seen from slightly lower "
                 "by the end. No zoom in, no zoom out, no push in, no pull back, no roll."),
    },
    # ---------------------------------------------------------------- arcos
    "arco-der": {
        "etiqueta": "arco lento a la derecha",
        "head": ("Very slow circular arc around the subject to the RIGHT, constant focal length and "
                 "distance, no zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SHORT SLOW ARC TO THE RIGHT. The camera walks a very small arc "
                 "around the subject to the RIGHT, about 15 degrees of orbit for the whole clip, at "
                 "an even, unhurried speed, always keeping the subject centred on the same axis and "
                 "the same distance away. The move is a gentle parallax sweep, not a pan and not a "
                 "zoom: the lens keeps a constant focal length and focus, the horizon stays level, "
                 "no zoom in, no zoom out, no push in, no pull back."),
    },
    "arco-izq": {
        "etiqueta": "arco lento a la izquierda",
        "head": ("Very slow circular arc around the subject to the LEFT, constant focal length and "
                 "distance, no zoom in or out."),
        "tail": ("CAMERA MOVE — ONE SHORT SLOW ARC TO THE LEFT. The camera walks a very small arc "
                 "around the subject to the LEFT, about 15 degrees of orbit for the whole clip, at "
                 "an even, unhurried speed, always keeping the subject centred on the same axis and "
                 "the same distance away. The move is a gentle parallax sweep, not a pan and not a "
                 "zoom: the lens keeps a constant focal length and focus, the horizon stays level, "
                 "no zoom in, no zoom out, no push in, no pull back."),
    },
    # -------------------------------------------------------------- estatica
    "loop": {
        "etiqueta": "loop perfecto (último frame = primero)",
        "head": ("Seamless loop with a locked-off camera: the clip starts and ends on exactly the same "
                 "frame, the camera does not move."),
        "tail": ("SEAMLESS LOOP — LOCKED-OFF CAMERA. The camera is fixed on a tripod and does not move "
                 "for the whole clip: same framing, same horizon, same focal length, same subject size "
                 "in the first frame and in the last frame, no pan, no tilt, no dolly, no orbit, no "
                 "parallax, no handheld shake, no zoom in, no zoom out. The clip is designed to repeat "
                 "endlessly, so the motion inside the frame is cyclic and comes back to where it "
                 "started: the mist drifts and returns, the candles flicker and settle, the smoke curls "
                 "and settles back, the lanterns swing and come back to rest, particles float and "
                 "return, the light breathes brighter and then dimmer, ending exactly on the brightness "
                 "of the first frame. The last frame is visually identical to the first frame, so the "
                 "loop point is invisible."),
    },
    "estatica": {
        "etiqueta": "cámara fija",
        "head": ("Locked-off static camera, fixed frame, constant focal length, no movement of the "
                 "camera at all."),
        "tail": ("CAMERA — COMPLETELY LOCKED OFF. The camera sits on a heavy tripod and does not move "
                 "for the whole clip: the same framing, the same horizon, the same focal length and "
                 "the same subject size in the first frame and in the last frame, rock-steady, no "
                 "pan, no tilt, no dolly, no crane, no orbit, no parallax, no handheld shake. All "
                 "the movement happens inside the frame: mist drifting, candles flickering, "
                 "particles and pollen floating, cloth and macrame swinging very slowly, water "
                 "rippling, smoke curling through the beams, light breathing slowly brighter and "
                 "dimmer."),
    },
}


_MARCAS_CABEZA = (_VIEJO_STATIC_HEAD,) + tuple(m["head"] + " " for m in CAM_MOVES.values())

# Cualquier cola que haya quedado pegada de una asignacion anterior (se calcula de las
# propias definiciones, asi una variante nueva no puede dejar el prompt sucio).
_MARCAS_COLA_TODAS = tuple(dict.fromkeys(
    ["\n\nSTATIC CAMERA, FIXED FRAME.", "\n\nSTATIC SHOT.",
     "\n\nOne single camera move for the whole clip"]
    + ["\n\n" + m["tail"][:30] for m in CAM_MOVES.values()]
))


def limpiar(prompt: str) -> str:
    """Devuelve solo la descripcion de la escena, sin ningun bloque de camara."""
    t = (prompt or "").strip()
    cortes = [t.find(m) for m in _MARCAS_COLA_TODAS if m in t]
    if cortes:
        t = t[:min(cortes)].strip()
    for h in _MARCAS_CABEZA:
        if t.startswith(h):
            t = t[len(h):].strip()
    return t


def aplicar(base: str, nombre: str) -> str:
    """Arma el prompt final: cabeza corta + escena + bloque de camara + cierre."""
    mov = CAM_MOVES[nombre]
    return (f"{mov['head']} {base}\n\n{mov['tail']}\n\n{_CIERRE}").strip()


def por_indice(n: int) -> str:
    """Movimiento que le toca al item numero n de la cola (rotacion estable)."""
    return ORDEN[n % len(ORDEN)]
