use crate::codec::{SomeIpSerialize, SomeIpDeserialize};
use crate::sd::entries::SdEntry;
use crate::sd::options::SdOption;
use std::io::{Result, Write, Read};

#[derive(Debug, Clone)]
/// [PRS_SOMEIPSD_00016] SD Header Format
pub struct SdPacket {
    /// [PRS_SOMEIPSD_00278] Reboot Flag, Unicast Flag
    pub flags: u8,
    pub entries: Vec<SdEntry>,
    pub options: Vec<SdOption>,
}

impl SomeIpSerialize for SdPacket {
    fn serialize<W: Write>(&self, writer: &mut W) -> Result<()> {
        // Flags
        writer.write_all(&[self.flags])?;
        // Reserved (24 bits)
        writer.write_all(&[0x00, 0x00, 0x00])?;
        
        // Entries Array (Length + Data)
        // We need to calculate length.
        let mut enc_entries = Vec::new();
        for e in &self.entries {
            e.serialize(&mut enc_entries)?;
        }
        let entries_len = enc_entries.len() as u32;
        writer.write_all(&entries_len.to_be_bytes())?;
        writer.write_all(&enc_entries)?;
        
        // Options Array
        let mut enc_opts = Vec::new();
        for o in &self.options {
            o.serialize(&mut enc_opts)?;
        }
        let opts_len = enc_opts.len() as u32;
        writer.write_all(&opts_len.to_be_bytes())?;
        writer.write_all(&enc_opts)?;
        
        Ok(())
    }
}

impl SomeIpDeserialize for SdPacket {
    fn deserialize<R: Read>(reader: &mut R) -> Result<Self> {
        let mut header_buf = [0u8; 4]; // Flags(1) + Res(3)
        reader.read_exact(&mut header_buf)?;
        let flags = header_buf[0];

        // Entries Length
        let mut entries_len_buf = [0u8; 4];
        reader.read_exact(&mut entries_len_buf)?;
        let entries_len = u32::from_be_bytes(entries_len_buf);

        // Read Entries
        let mut entries = Vec::new();
        {
            let mut current_entries_len = 0;
            while current_entries_len < entries_len {
                let entry = SdEntry::deserialize(reader)?;
                entries.push(entry);
                current_entries_len += 16;
            }
        }

        // Options Length
        let mut options_len_buf = [0u8; 4];
        reader.read_exact(&mut options_len_buf)?;
        let options_len = u32::from_be_bytes(options_len_buf);
        
        let mut options = Vec::new();
        {
            let mut options_reader = reader.take(options_len as u64);
            while options_reader.limit() > 0 {
                 // We need to peek or read the length of the next option to know if we are done?
                 // No, `options_reader` will return EOF when limit is reached.
                 // But `SdOption::deserialize` will try to read length(2).
                 // If we are at EOF, it fails.
                 // We need to check if we have consumed `options_len`.
                 // `options_reader.limit()` tells us how many bytes left.
                 
                 
                 // We can attempt to deserialize.
                 let opt = SdOption::deserialize(&mut options_reader)?;
                 
                 // How many bytes did we consume?
                 // SdOption deserialize reads: 2 (len) + 1 (type) + length (payload).
                 // Total = 3 + length.
                 // We can calculate it again or trust the reader limit Decremented?
                 // `Take` updates its limit as we read.
                 // So we just strict loop until limit is 0.
                 options.push(opt);
                 
                 // Update current loop counter just in case, but `limit()` check is key.
                 // current_options_len = options_len - (options_reader.limit() as u32);
            }
        } // options_reader dropped here, releasing borrow on reader

        Ok(SdPacket {
            flags,
            entries,
            options,
        })
    }
}
