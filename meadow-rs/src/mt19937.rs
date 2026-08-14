//! MT19937 matching CPython's `random.Random` exactly, including seeding
//! (`init_by_array` over the seed integer's 32-bit limbs) and the
//! `getrandbits`/`_randbelow` paths. Bit-for-bit parity with Python lets the
//! Rust and Python scripted sweeps produce identical stochastic episodes.

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

pub struct PyRandom {
    mt: [u32; N],
    index: usize,
}

impl PyRandom {
    /// Equivalent to `random.Random(seed)` for a non-negative integer seed.
    pub fn new(seed: u64) -> Self {
        let mut key = Vec::new();
        let mut s = seed;
        loop {
            key.push((s & 0xffff_ffff) as u32);
            s >>= 32;
            if s == 0 {
                break;
            }
        }
        let mut rng = PyRandom { mt: [0; N], index: N };
        rng.init_by_array(&key);
        rng
    }

    fn init_genrand(&mut self, s: u32) {
        self.mt[0] = s;
        for i in 1..N {
            self.mt[i] = (1812433253u32
                .wrapping_mul(self.mt[i - 1] ^ (self.mt[i - 1] >> 30)))
            .wrapping_add(i as u32);
        }
        self.index = N;
    }

    fn init_by_array(&mut self, key: &[u32]) {
        self.init_genrand(19650218);
        let mut i = 1usize;
        let mut j = 0usize;
        let mut k = N.max(key.len());
        while k > 0 {
            self.mt[i] = (self.mt[i]
                ^ ((self.mt[i - 1] ^ (self.mt[i - 1] >> 30)).wrapping_mul(1664525)))
            .wrapping_add(key[j])
            .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            if j >= key.len() {
                j = 0;
            }
            k -= 1;
        }
        k = N - 1;
        while k > 0 {
            self.mt[i] = (self.mt[i]
                ^ ((self.mt[i - 1] ^ (self.mt[i - 1] >> 30)).wrapping_mul(1566083941)))
            .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            k -= 1;
        }
        self.mt[0] = 0x8000_0000;
        self.index = N;
    }

    fn genrand_u32(&mut self) -> u32 {
        if self.index >= N {
            for i in 0..N {
                let y = (self.mt[i] & UPPER_MASK) | (self.mt[(i + 1) % N] & LOWER_MASK);
                let mut next = self.mt[(i + M) % N] ^ (y >> 1);
                if y & 1 != 0 {
                    next ^= MATRIX_A;
                }
                self.mt[i] = next;
            }
            self.index = 0;
        }
        let mut y = self.mt[self.index];
        self.index += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^= y >> 18;
        y
    }

    /// `random.Random.getrandbits(k)` for 0 < k <= 32.
    pub fn getrandbits(&mut self, k: u32) -> u32 {
        debug_assert!((1..=32).contains(&k));
        self.genrand_u32() >> (32 - k)
    }

    /// `random.Random._randbelow(n)` (the getrandbits rejection loop).
    pub fn randbelow(&mut self, n: u32) -> u32 {
        debug_assert!(n > 0);
        let k = 32 - n.leading_zeros();
        loop {
            let r = self.getrandbits(k);
            if r < n {
                return r;
            }
        }
    }

    /// `random.Random.randint(a, b)`.
    pub fn randint(&mut self, a: u32, b: u32) -> u32 {
        a + self.randbelow(b - a + 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raw_outputs_match_cpython() {
        let mut rng = PyRandom::new(0);
        let raw: Vec<u32> = (0..5).map(|_| rng.getrandbits(32)).collect();
        assert_eq!(raw, vec![3626764237, 1654615998, 3255389356, 3823568514, 1806341205]);
    }

    #[test]
    fn randint_streams_match_cpython() {
        let expect: &[(u64, [u32; 16])] = &[
            (0, [3, 3, 0, 2, 3, 3, 2, 3, 2, 1, 1, 2, 1, 0, 2, 1]),
            (1, [1, 0, 2, 0, 3, 3, 3, 3, 1, 0, 3, 0, 3, 3, 0, 3]),
            (4000, [3, 3, 3, 1, 3, 2, 3, 0, 2, 2, 2, 0, 2, 0, 0, 3]),
            (4007, [1, 2, 1, 1, 3, 0, 3, 1, 1, 3, 3, 0, 3, 0, 1, 2]),
            (29007, [0, 2, 0, 2, 0, 0, 3, 0, 3, 3, 2, 1, 0, 2, 0, 3]),
        ];
        for (seed, stream) in expect {
            let mut rng = PyRandom::new(*seed);
            let got: Vec<u32> = (0..16).map(|_| rng.randint(0, 3)).collect();
            assert_eq!(&got[..], &stream[..], "seed {seed}");
        }
    }

    #[test]
    fn multi_limb_seed_matches_cpython() {
        let mut rng = PyRandom::new(123456789012345);
        let got: Vec<u32> = (0..8).map(|_| rng.randint(0, 3)).collect();
        assert_eq!(got, vec![1, 2, 3, 1, 0, 1, 3, 1]);
    }
}
