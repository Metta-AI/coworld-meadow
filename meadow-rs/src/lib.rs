//! meadow-rs — zero-dependency Rust port of the Meadow commons-game
//! simulation core: rules engine, scripted policies (with a CPython-parity
//! MT19937 for the stochastic ones), planner-optimum DP, and the scripted
//! experiment driver. LLM seats and plotting stay in Python — those are
//! network- and library-bound, not compute-bound.

pub mod engine;
pub mod headless;
pub mod json;
pub mod mt19937;
pub mod planner;
pub mod policies;
pub mod pyfmt;
pub mod scripted;
