//! Dependency-free Rust library called through a C ABI by the ROS C++ node.
#[no_mangle]
pub extern "C" fn ros_demo_transform(sequence: u64) -> u64 {
    sequence.wrapping_mul(sequence).wrapping_add(3 * sequence).wrapping_add(7)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn known_values() {
        assert_eq!(ros_demo_transform(0), 7);
        assert_eq!(ros_demo_transform(1), 11);
        assert_eq!(ros_demo_transform(39), 1645);
    }
}
