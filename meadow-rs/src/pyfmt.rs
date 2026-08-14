//! Python-compatible float rounding and JSON float formatting.
//!
//! `py_round` reproduces CPython's `round(x, n)` (correctly-rounded decimal,
//! ties to even) and `py_repr` reproduces `repr(float)` (shortest round-trip,
//! integral floats keep a trailing `.0`) for the value ranges the meadow
//! produces. Both lean on Rust's exact float formatting, which rounds decimal
//! digit sequences to nearest with ties to even, same as CPython.

pub fn py_round(x: f64, ndigits: usize) -> f64 {
    format!("{:.*}", ndigits, x).parse::<f64>().expect("fixed-precision f64 reparses")
}

pub fn py_repr(x: f64) -> String {
    let s = format!("{}", x);
    if s.contains('.') || s.contains('e') || s.contains("inf") || s.contains("NaN") {
        s
    } else {
        format!("{s}.0")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_matches_cpython_reference_cases() {
        let cases: &[(f64, usize, f64)] = &[
            (2.675, 2, 2.67),
            (0.125, 2, 0.12),
            (0.375, 2, 0.38),
            (60.0, 2, 60.0),
            (8.4499999, 2, 8.45),
            (0.30000000000000004, 4, 0.3),
            (585.0000000000001, 3, 585.0),
            (94.5, 3, 94.5),
            (-0.1355, 4, -0.1355),
            (22.15, 3, 22.15),
        ];
        for &(x, n, want) in cases {
            assert_eq!(py_round(x, n), want, "round({x}, {n})");
        }
    }

    #[test]
    fn repr_matches_cpython_shapes() {
        assert_eq!(py_repr(585.0), "585.0");
        assert_eq!(py_repr(0.5), "0.5");
        assert_eq!(py_repr(-0.0), "-0.0");
        assert_eq!(py_repr(0.30000000000000004), "0.30000000000000004");
    }
}
