use super::traits::{SomeIpSerialize, SomeIpDeserialize};
use std::io::{Result, Write, Read};

macro_rules! impl_primitive {
    ($type:ty, $write_method:ident, $read_method:ident, $bytes:expr) => {
        impl SomeIpSerialize for $type {
            fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
                writer.write_all(&self.to_be_bytes())
            }
        }

        impl SomeIpDeserialize for $type {
            fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
                let mut buf = [0u8; $bytes];
                reader.read_exact(&mut buf)?;
                Ok(<$type>::from_be_bytes(buf))
            }
        }
    };
}

impl_primitive!(u8, write_u8, read_u8, 1);
impl_primitive!(u16, write_u16, read_u16, 2);
impl_primitive!(u32, write_u32, read_u32, 4);
impl_primitive!(u64, write_u64, read_u64, 8);

impl_primitive!(i8, write_i8, read_i8, 1);
impl_primitive!(i16, write_i16, read_i16, 2);
impl_primitive!(i32, write_i32, read_i32, 4);
impl_primitive!(i64, write_i64, read_i64, 8);

impl_primitive!(f32, write_f32, read_f32, 4);
impl_primitive!(f64, write_f64, read_f64, 8);

// Boolean: 1 byte (0x00 = false, 0x01 = true)
impl SomeIpSerialize for bool {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        writer.write_all(&[*self as u8])
    }
}

impl SomeIpDeserialize for bool {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        let mut buf = [0u8; 1];
        reader.read_exact(&mut buf)?;
        Ok(buf[0] != 0)
    }
}
