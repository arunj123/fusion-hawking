use std::io::{Result, Write, Read};

// Trait for Types that can be serialized to SOME/IP format
pub trait SomeIpSerialize {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()>;
}

// Trait for Types that can be deserialized from SOME/IP format
pub trait SomeIpDeserialize: Sized {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self>;
}
