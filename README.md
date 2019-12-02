# Message-Board protocol
This file describes the protocol that is used by client.py and server.py

The timeline of the communications is as follows, all communications happen in series

    c -> s, length of request (4 bytes, big endian)
    c -> s, utf-8 encoded json query object [the body of the request]
    s -> c, length of response (4 bytes, big endian)
    s -> c, utf-8 encoded json response object [the body of the response]

Key:

    a -> b, a sends a message to b
    c, client
    s, server

## Queries

The format of a query can be defined as follows,

    {
        method: "GET_BOARDS" | "GET_MESSAGES" | "POST_MESSAGE"
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