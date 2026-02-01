use crate::codec::{SomeIpSerialize, SomeIpDeserialize};
use std::io::{Result, Write, Read};

#[derive(Debug, Clone, PartialEq)]
pub struct RustMathRequest {
    pub op: i32,
    pub a: i32,
    pub b: i32,
}

impl SomeIpSerialize for RustMathRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.op.serialize(writer)?;
        self.a.serialize(writer)?;
        self.b.serialize(writer)?;
        Ok(())
    }
}

impl SomeIpDeserialize for RustMathRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(RustMathRequest {
            op: <i32>::deserialize(reader)?,
            a: <i32>::deserialize(reader)?,
            b: <i32>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RustMathResponse {
    pub result: i32,
}

impl SomeIpSerialize for RustMathResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}

impl SomeIpDeserialize for RustMathResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(RustMathResponse {
            result: <i32>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PyStringRequest {
    pub op: i32,
    pub text: String,
}

impl SomeIpSerialize for PyStringRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.op.serialize(writer)?;
        self.text.serialize(writer)?;
        Ok(())
    }
}

impl SomeIpDeserialize for PyStringRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(PyStringRequest {
            op: <i32>::deserialize(reader)?,
            text: <String>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PyStringResponse {
    pub result: String,
}

impl SomeIpSerialize for PyStringResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.result.serialize(writer)?;
        Ok(())
    }
}

impl SomeIpDeserialize for PyStringResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(PyStringResponse {
            result: <String>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CppSortRequest {
    pub method: i32,
    pub data: Vec<i32>,
}

impl SomeIpSerialize for CppSortRequest {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.method.serialize(writer)?;
        self.data.serialize(writer)?;
        Ok(())
    }
}

impl SomeIpDeserialize for CppSortRequest {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(CppSortRequest {
            method: <i32>::deserialize(reader)?,
            data: <Vec<i32>>::deserialize(reader)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CppSortResponse {
    pub sorted_data: Vec<i32>,
}

impl SomeIpSerialize for CppSortResponse {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        self.sorted_data.serialize(writer)?;
        Ok(())
    }
}

impl SomeIpDeserialize for CppSortResponse {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        Ok(CppSortResponse {
            sorted_data: <Vec<i32>>::deserialize(reader)?,
        })
    }
}
