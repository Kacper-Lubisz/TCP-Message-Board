# Message-Board protocol
This file describes the protocol that is used by client.py and server.py

The protocol uses a 5 second timeout, if no response is received within the timeout the transaction is to be abandoned.

The timeline of the communications is as follows:

    1       c -> s, length of request (8 bytes, big endian)
    2       c -> s, utf-8 encoded json query object [the body of the request]
    
                loop until 2 is complete starting after delay period (less than timeout)
    2.1         s -> c, 8 zero bytes
    2.2         s -> c, length or recieved buffer (8 zero bytes, big endian)
                 
    3       s -> c, length of response (8 bytes, big endian)
    4       s -> c, utf-8 encoded json response object [the body of the response]
    
Key:

    1 a -> b, a sends a message to b
    
        b -> a happening in parallel (indent) 
        
    c, client
    
    s, server

## Queries

The format of a query can be defined as follows,

    {
        method: "GET_BOARDS" | "GET_MESSAGES" | "POST_MESSAGE", request type
        version: string, the version of the protocol being used
        **args: depending on method
    }

The arguments for each method are as follow,

    GET_BOARDS {}
    
    GET_MESSAGES {
        board: string, the board to get messages from
    }
    
    POST_MESSAGE {
        board: string, the board to be posted to
        title: string, the title of the post
        content: string, the content of the post
    }

## Responses

All responses are in the format,

    {
        success: boolean
        **args: depending on success and method
    }

In the case where 'success' is false

    {
        success: false
        error:string, A message describing why the query failed
    }

For each successful method,

    GET_BOARDS {
        success: true,
        boards: string[], the names of all the boards
    }
    
    GET_MESSAGES {
        success: true
        messages: {
            title:string, the title of the post
            date:string, the date of the post in the format 'YYYYMMDD'
            time:string, the time of the post in the format 'HHMMSS'
            contents:string, the contents of the message
        }[]
    }
    
    POST_MESSAGE {
        success: true
    }