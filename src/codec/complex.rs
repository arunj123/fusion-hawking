use super::traits::{SomeIpSerialize, SomeIpDeserialize};
use std::io::{Result, Write, Read};

// Strings are typically UTF-8 with a BOM or length prefix in SOME/IP,
// but for raw serialization, we'll treat them as a sequence of bytes.
// The Length field is usually handled by the container (struct) logic in SOME/IP.
impl SomeIpSerialize for String {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
         // Prefix with length to be consistent with Deserializer
         let len = self.len() as u32;
         writer.write_all(&len.to_be_bytes())?;
         writer.write_all(self.as_bytes())
    }
}

impl SomeIpDeserialize for String {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        let mut length_bytes = [0u8; 4];
        reader.read_exact(&mut length_bytes)?;
        let len = u32::from_be_bytes(length_bytes) as usize;
        let mut buffer = vec![0u8; len];
        reader.read_exact(&mut buffer)?;
        
        String::from_utf8(buffer).map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidData, "Invalid UTF-8"))
    }
}

// Vec<T> Serialization - Prefixed with 32-bit Length (Bytes)
impl<T: SomeIpSerialize> SomeIpSerialize for Vec<T> {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        // We need to know the byte length of the serialized payload.
        // Since we don't have a 'size_hint' trait, we must buffer.
        let mut buffer = Vec::new();
        for item in self {
            item.serialize(&mut buffer)?;
        }
        
        let len = buffer.len() as u32;
        writer.write_all(&len.to_be_bytes())?;
        writer.write_all(&buffer)?;
        Ok(())
    }
}

// Vec<T> Deserialization - Assumes 32-bit Length Prefix (Bytes)
impl<T: SomeIpDeserialize> SomeIpDeserialize for Vec<T> {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        let mut length_bytes = [0u8; 4];
        reader.read_exact(&mut length_bytes)?;
        let total_bytes = u32::from_be_bytes(length_bytes) as usize;
        
        let mut handle = reader.take(total_bytes as u64);
        let mut vec = Vec::new();
        
        // Read all into buffer, then parse buffer.
        let mut buffer = vec![0u8; total_bytes];
        handle.read_exact(&mut buffer)?;
        
        let mut cursor = std::io::Cursor::new(buffer);
        let len = cursor.get_ref().len() as u64;
        
        while cursor.position() < len {
             vec.push(T::deserialize(&mut cursor)?);
        }
        
        Ok(vec)
    }
}
