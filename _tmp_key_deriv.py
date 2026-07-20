def _key_derivations(key_space: dict[str, Any]) -> list[dict[str, Any]]:
    key_domains = {str(item.get("id")): item.get("values") for item in _iter_items(key_space.get("fields"))}
    derived: list[dict[str, Any]] = []
    add = derived.append
    add(_derived("VAR_KEY_ISTND", "int", key_domains.get("KEY_ISTND", [0, 1]), _ite(_eq_csv("Input_Layout", "TND"), 1, 0), "Input_Layout == TND"))
    add(_derived("VAR_KEY_ISROPE", "int", key_domains.get("KEY_ISROPE", [0, 1]), _ite(_eq_csv("rope", 1), 1, 0), "rope == 1"))
    add(_derived("VAR_KEY_ISATTENMASK", "int", key_domains.get("KEY_ISATTENMASK", [0, 1]), _ite(_ne_csv("Atten_mask_shape", "NONE"), 1, 0), "Atten_mask_shape != NONE"))
    add(
        _derived(
            "VAR_KEY_ISPSE",
            "int",
            key_domains.get("KEY_ISPSE", [0, 1]),
            _ite({"op": "or", "args": [_ne_csv("PSE_shape", "NONE"), _ne_csv("PSE_type", 0)]}, 1, 0),
            "PSE_shape != NONE or PSE_type != 0",
        )
    )
    add(
        _derived(
            "VAR_KEY_ISDROP",
            "int",
            key_domains.get("KEY_ISDROP", [0, 1]),
            _ite({"op": "or", "args": [_ne_csv("Drop_Out_Possibility", 1), _eq_csv("inner_drop", 1)]}, 1, 0),
            "Drop_Out_Possibility != 1 or inner_drop == 1",
        )
    )
    add(_derived("VAR_KEY_ISNEQUAL", "int", key_domains.get("KEY_ISNEQUAL", [0, 1]), _ite(_ne_csv_vars("N1", "N2"), 1, 0), "N1 != N2"))
    add(_derived("VAR_KEY_ISDNOEQUAL", "int", key_domains.get("KEY_ISDNOEQUAL", [0, 1]), _ite(_ne_csv_vars("D", "D_V"), 1, 0), "D != D_V"))
    add(_derived("VAR_KEY_INPUTDTYPE", "int", key_domains.get("KEY_INPUTDTYPE", [0, 1, 2]), _dtype_expr("Dtype"), "Dtype bucket"))
    add(_derived("VAR_KEY_OUTDTYPE", "int", key_domains.get("KEY_OUTDTYPE", [0, 1, 2]), _dtype_expr("out_dtype"), "out_dtype bucket"))
    add(_derived("VAR_KEY_S1TEMPLATENUM", "int", key_domains.get("KEY_S1TEMPLATENUM", [0, 64, 128, 512]), _bucket_expr("S1", [512, 128, 64], [512, 128, 64], 0), "S1 template bucket"))
    add(_derived("VAR_KEY_S2TEMPLATENUM", "int", key_domains.get("KEY_S2TEMPLATENUM", [0, 128, 256, 512]), _bucket_expr("S2", [512, 256, 128], [512, 256, 128], 0), "S2 template bucket"))
    add(_derived("VAR_KEY_DTEMPLATENUM", "int", key_domains.get("KEY_DTEMPLATENUM", [0, 64, 128, 192, 256]), _bucket_expr("D", [256, 192, 128, 64], [256, 192, 128, 64], 0), "D template bucket"))
    return derived


