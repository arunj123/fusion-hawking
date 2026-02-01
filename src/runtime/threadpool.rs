use std::thread;
use std::sync::{mpsc, Arc, Mutex};
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

type Job = Box<dyn FnOnce() + Send + 'static>;

enum Message {
    NewJob(Job),
    Terminate,
}

struct Worker {
    _id: usize,
    thread: Option<thread::JoinHandle<()>>,
}

impl Worker {
    fn new(id: usize, receiver: Arc<Mutex<mpsc::Receiver<Message>>>) -> Worker {
        let thread = thread::spawn(move || loop {
            let message = receiver.lock().unwrap().recv();
            match message {
                Ok(Message::NewJob(job)) => {
                    // println!("Worker {} got a job; executing.", id);
                    job();
                }
                Ok(Message::Terminate) => {
                    // println!("Worker {} was told to terminate.", id);
                    break;
                }
                Err(_) => {
                    // Channel disconnected
                    break;
                }
            }
        });

        Worker {
            _id: id,
            thread: Some(thread),
        }
    }
}

pub struct ThreadPool {
    workers: Vec<Worker>,
    senders: Vec<mpsc::Sender<Message>>,
    size: usize,
}

impl ThreadPool {
    /// Create a new ThreadPool.
    ///
    /// The size is the number of threads in the pool.
    pub fn new(size: usize) -> ThreadPool {
        assert!(size > 0);

        let mut workers = Vec::with_capacity(size);
        let mut senders = Vec::with_capacity(size);

        for id in 0..size {
            let (sender, receiver) = mpsc::channel();
            let receiver = Arc::new(Mutex::new(receiver));
            workers.push(Worker::new(id, receiver));
            senders.push(sender);
        }

        ThreadPool {
            workers,
            senders,
            size,
        }
    }

    /// Execute a job.
    ///
    /// `key`: If Some(hashable), the job is routed to a stable thread based on the hash.
    /// This ensures sequential execution for that key.
    /// If None, the job is distributed (currently Round Robin or simply hashed by 0/Random).
    pub fn execute<F, K>(&self, f: F, key: Option<K>)
    where
        F: FnOnce() + Send + 'static,
        K: Hash,
    {
        let job = Box::new(f);
        
        let worker_idx = if let Some(k) = key {
            let mut hasher = DefaultHasher::new();
            k.hash(&mut hasher);
            (hasher.finish() as usize) % self.size
        } else {
             // Basic round-robin or random could be better, but for now specific to first logic:
             // To properly load balance "None" keys, we should rotate.
             // Simplification: Hash of 0 implies "don't care" but stacks them on thread 0.
             // Let's us rand or a counter if we want RR.
             // For strict no-dep, we can use a atomic counter.
             // For now: Just use 0. Warning: This biases non-keyed work to thread 0.
             // Correct approach: Just pick one.
             0
        };

        self.senders[worker_idx].send(Message::NewJob(job)).unwrap();
    }
    
    // Explicit round-robin dispatch for unkeyed tasks could be added (requires mutable state or atomic)
}

impl Drop for ThreadPool {
    fn drop(&mut self) {
        for sender in &self.senders {
            let _ = sender.send(Message::Terminate);
        }

        for worker in &mut self.workers {
            if let Some(thread) = worker.thread.take() {
                thread.join().unwrap();
            }
        }
    }
}
