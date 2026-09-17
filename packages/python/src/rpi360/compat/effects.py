import warnings


def canonical_effect(name):
    if name == "rabbit-hole":
        warnings.warn(
            "rabbit-hole is deprecated; use inverted-tiny-planet",
            DeprecationWarning,
            stacklevel=3,
        )
        return "inverted-tiny-planet"
    return name
