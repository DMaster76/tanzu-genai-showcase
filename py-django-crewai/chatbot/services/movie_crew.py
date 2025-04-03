"""
Movie Chatbot CrewAI implementation.
This module contains the CrewAI crew for the movie chatbot.
"""

import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import tmdbsimple as tmdb
from crewai import Agent, Task, Crew
from langchain.tools import tool
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

class MovieCrewManager:
    """Manager for the movie recommendation crew."""
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "gpt-3.5-turbo",
        tmdb_api_key: Optional[str] = None,
        user_location: Optional[str] = None
    ):
        """
        Initialize the MovieCrewManager.
        
        Args:
            api_key: LLM API key
            base_url: Optional custom endpoint URL for the LLM API
            model: Model name to use
            tmdb_api_key: API key for The Movie Database (TMDb)
            user_location: Optional user location string
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.tmdb_api_key = tmdb_api_key
        self.user_location = user_location
        
        # Configure TMDb API if key is provided
        if tmdb_api_key:
            tmdb.API_KEY = tmdb_api_key
    
    def create_llm(self, temperature: float = 0.5) -> ChatOpenAI:
        """Create an LLM instance with the specified configuration."""
        config = {
            "openai_api_key": self.api_key,
            "model": self.model,
            "temperature": temperature,
        }
        
        if self.base_url:
            config["openai_api_base"] = self.base_url
        
        return ChatOpenAI(**config)
    
    def process_query(self, query: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Process a user query and return movie recommendations.
        
        Args:
            query: The user's query
            conversation_history: List of previous messages in the conversation
            
        Returns:
            Dict with response text and movie recommendations
        """
        # Create the LLM
        llm = self.create_llm()
        
        # Create the agents
        movie_finder = self._create_movie_finder_agent(llm)
        recommender = self._create_recommendation_agent(llm)
        theater_finder = self._create_theater_finder_agent(llm)
        
        # Create the tasks
        context = {
            "user_query": query, 
            "conversation_history": conversation_history,
            "user_location": self.user_location or "Unknown"
        }
        
        find_movies_task = Task(
            description="Find movies that match the user's criteria",
            agent=movie_finder,
            context=context,
            expected_output="A JSON list of relevant movies with title, overview, release date, and TMDb ID"
        )
        
        recommend_movies_task = Task(
            description="Recommend the top 3 movies from the list that best match the user's preferences",
            agent=recommender,
            context=lambda: {
                **context,
                "movies": find_movies_task.output
            },
            expected_output="A JSON list of the top 3 recommended movies with explanations"
        )
        
        find_theaters_task = Task(
            description="Find theaters showing the recommended movies near the user's location",
            agent=theater_finder,
            context=lambda: {
                **context,
                "recommended_movies": recommend_movies_task.output
            },
            expected_output="A JSON list of theaters showing the recommended movies with showtimes"
        )
        
        # Create the crew
        crew = Crew(
            agents=[movie_finder, recommender, theater_finder],
            tasks=[find_movies_task, recommend_movies_task, find_theaters_task],
            verbose=True
        )
        
        # Execute the crew
        try:
            result = crew.kickoff()
            logger.info(f"Crew result: {result}")
            
            # Parse the final output and format the response
            theaters_data = self._parse_json_output(find_theaters_task.output)
            recommendations = self._parse_json_output(recommend_movies_task.output)
            
            # Combine recommendations with theater data
            movies_with_theaters = []
            for movie in recommendations:
                movie_theaters = []
                for theater in theaters_data:
                    if theater.get("movie_id") == movie.get("tmdb_id"):
                        movie_theaters.append(theater)
                
                movie_with_theaters = {**movie, "theaters": movie_theaters}
                movies_with_theaters.append(movie_with_theaters)
            
            # Format a nice response message
            response_message = self._format_response(movies_with_theaters, query)
            
            return {
                "response": response_message,
                "movies": movies_with_theaters
            }
        
        except Exception as e:
            logger.error(f"Error executing crew: {str(e)}")
            return {
                "response": "I apologize, but I encountered an error while searching for movies. Please try again with a different request.",
                "movies": []
            }
    
    def _create_movie_finder_agent(self, llm: ChatOpenAI) -> Agent:
        """Create a movie finder agent."""
        
        @tool
        def search_movies(query: str) -> str:
            """
            Search for movies based on a query.
            Args:
                query: The search query for movies
            Returns:
                JSON string of movie search results
            """
            try:
                search = tmdb.Search()
                response = search.movie(query=query)
                
                movies = []
                for movie in response.get('results', [])[:10]:  # Limit to 10 results
                    movies.append({
                        "tmdb_id": movie.get('id'),
                        "title": movie.get('title'),
                        "overview": movie.get('overview'),
                        "release_date": movie.get('release_date'),
                        "poster_url": f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get('poster_path') else None,
                        "rating": movie.get('vote_average')
                    })
                
                return json.dumps(movies)
            except Exception as e:
                logger.error(f"Error searching movies: {str(e)}")
                return json.dumps([])
        
        @tool
        def get_movie_details(movie_id: int) -> str:
            """
            Get detailed information about a movie.
            Args:
                movie_id: The TMDb ID of the movie
            Returns:
                JSON string of movie details
            """
            try:
                movie = tmdb.Movies(movie_id)
                response = movie.info()
                
                credits = movie.credits()
                
                # Extract director and top cast
                directors = [person.get('name') for person in credits.get('crew', []) if person.get('job') == 'Director']
                cast = [person.get('name') for person in credits.get('cast', [])[:5]]  # Top 5 cast members
                
                # Get genres
                genres = [genre.get('name') for genre in response.get('genres', [])]
                
                movie_details = {
                    "tmdb_id": response.get('id'),
                    "title": response.get('title'),
                    "overview": response.get('overview'),
                    "release_date": response.get('release_date'),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{response.get('poster_path')}" if response.get('poster_path') else None,
                    "rating": response.get('vote_average'),
                    "runtime": response.get('runtime'),
                    "genres": genres,
                    "directors": directors,
                    "cast": cast
                }
                
                return json.dumps(movie_details)
            except Exception as e:
                logger.error(f"Error getting movie details: {str(e)}")
                return json.dumps({})
        
        @tool
        def get_now_playing_movies() -> str:
            """
            Get movies that are currently playing in theaters.
            Returns:
                JSON string of movies currently in theaters
            """
            try:
                movies = tmdb.Movies()
                response = movies.now_playing()
                
                now_playing = []
                for movie in response.get('results', [])[:15]:  # Limit to 15 results
                    now_playing.append({
                        "tmdb_id": movie.get('id'),
                        "title": movie.get('title'),
                        "overview": movie.get('overview'),
                        "release_date": movie.get('release_date'),
                        "poster_url": f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get('poster_path') else None,
                        "rating": movie.get('vote_average')
                    })
                
                return json.dumps(now_playing)
            except Exception as e:
                logger.error(f"Error getting now playing movies: {str(e)}")
                return json.dumps([])
        
        return Agent(
            role="Movie Finder",
            goal="Find movies that match the user's criteria",
            backstory=(
                "You are an expert movie researcher with encyclopedic knowledge of films. "
                "Your job is to find movies that match what the user is looking for by "
                "understanding their preferences and using The Movie Database API to search."
            ),
            verbose=True,
            llm=llm,
            tools=[search_movies, get_movie_details, get_now_playing_movies]
        )
    
    def _create_recommendation_agent(self, llm: ChatOpenAI) -> Agent:
        """Create a movie recommendation agent."""
        return Agent(
            role="Movie Recommender",
            goal="Recommend the best movies for the user based on their preferences",
            backstory=(
                "You are a film critic and recommendation specialist who understands people's tastes. "
                "Your job is to analyze movie options and recommend the top 3 choices that will "
                "best match what the user is looking for."
            ),
            verbose=True,
            llm=llm
        )
    
    def _create_theater_finder_agent(self, llm: ChatOpenAI) -> Agent:
        """Create a theater finder agent."""
        
        @tool
        def get_nearby_theaters(location: str) -> str:
            """
            Find theaters near a location.
            NOTE: In a real implementation, this would use a real theater API or database.
            For this demo, we'll simulate theater data.
            
            Args:
                location: Location string (city, address, etc.)
            Returns:
                JSON string of nearby theaters
            """
            # Simulate finding theaters near the location
            # In a real implementation, this would use Google Maps API, Fandango, etc.
            
            # Mock data for demonstration purposes
            theaters = [
                {
                    "name": "AMC Metroplex 16",
                    "address": f"123 Main St, {location}",
                    "latitude": 37.7749,
                    "longitude": -122.4194,
                    "distance": "2.5 miles"
                },
                {
                    "name": "Regal Cinemas Downtown",
                    "address": f"456 Broadway, {location}",
                    "latitude": 37.7833,
                    "longitude": -122.4167,
                    "distance": "3.2 miles"
                },
                {
                    "name": "Cinemark City Center",
                    "address": f"789 Market St, {location}",
                    "latitude": 37.7879,
                    "longitude": -122.4074,
                    "distance": "1.8 miles"
                }
            ]
            
            return json.dumps(theaters)
        
        @tool
        def get_movie_showtimes(theater_name: str, movie_title: str) -> str:
            """
            Get showtimes for a movie at a specific theater.
            NOTE: In a real implementation, this would use a real showtimes API.
            For this demo, we'll simulate showtime data.
            
            Args:
                theater_name: Name of the theater
                movie_title: Title of the movie
            Returns:
                JSON string of showtimes
            """
            # Simulate finding showtimes
            # In a real implementation, this would use a movie showtimes API
            
            # Generate some realistic showtimes for today and tomorrow
            today = datetime.now()
            tomorrow = datetime.now().replace(day=today.day + 1)
            
            # Create showtime slots
            today_slots = [
                today.replace(hour=14, minute=30).isoformat(),
                today.replace(hour=17, minute=15).isoformat(),
                today.replace(hour=19, minute=45).isoformat(),
                today.replace(hour=22, minute=0).isoformat()
            ]
            
            tomorrow_slots = [
                tomorrow.replace(hour=13, minute=0).isoformat(),
                tomorrow.replace(hour=15, minute=30).isoformat(),
                tomorrow.replace(hour=18, minute=0).isoformat(),
                tomorrow.replace(hour=20, minute=30).isoformat()
            ]
            
            # Random formats
            formats = ["Standard", "IMAX", "3D", "Dolby Atmos"]
            
            # Create showtimes data
            showtimes = []
            
            # Today's showtimes
            for slot in today_slots:
                showtimes.append({
                    "theater": theater_name,
                    "movie": movie_title,
                    "start_time": slot,
                    "format": formats[len(showtimes) % len(formats)]
                })
            
            # Tomorrow's showtimes
            for slot in tomorrow_slots:
                showtimes.append({
                    "theater": theater_name,
                    "movie": movie_title,
                    "start_time": slot,
                    "format": formats[len(showtimes) % len(formats)]
                })
            
            return json.dumps(showtimes)
        
        return Agent(
            role="Theater Finder",
            goal="Find theaters showing the recommended movies near the user's location",
            backstory=(
                "You are a local cinema expert who knows all the theaters and showtimes in any area. "
                "Your job is to find where the recommended movies are playing near the user "
                "and provide accurate information about showtimes."
            ),
            verbose=True,
            llm=llm,
            tools=[get_nearby_theaters, get_movie_showtimes]
        )
    
    def _parse_json_output(self, output: str) -> List[Dict[str, Any]]:
        """
        Parse JSON output from a task, with error handling.
        
        Args:
            output: String that should contain JSON
            
        Returns:
            Parsed JSON as a Python object, or empty list/dict on error
        """
        try:
            # Try to extract JSON from the string if it's embedded in other text
            json_start = output.find("[")
            json_end = output.rfind("]") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = output[json_start:json_end]
                return json.loads(json_str)
            
            # If not a list, try as a dictionary
            json_start = output.find("{")
            json_end = output.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = output[json_start:json_end]
                return json.loads(json_str)
            
            # If all else fails, try parsing the whole output
            return json.loads(output)
        
        except json.JSONDecodeError:
            logger.error(f"Error parsing JSON output: {output}")
            # Return an empty list or dict depending on the expected output
            if output.strip().startswith("["):
                return []
            return {}
    
    def _format_response(self, movies: List[Dict[str, Any]], query: str) -> str:
        """
        Format a user-friendly response message.
        
        Args:
            movies: List of movie recommendations with theater data
            query: The original user query
            
        Returns:
            Formatted response message
        """
        if not movies:
            return (
                "I'm sorry, but I couldn't find any movies matching your request. "
                "Could you please try again with different criteria? For example, "
                "you can specify a genre like 'action' or 'comedy', or ask for "
                "recent releases."
            )
        
        response = f"Based on your interest in {query}, here are my top recommendations:\n\n"
        
        for i, movie in enumerate(movies, 1):
            response += f"{i}. {movie.get('title', 'Unknown movie')}"
            
            release_date = movie.get('release_date')
            if release_date:
                try:
                    release_year = datetime.strptime(release_date, "%Y-%m-%d").year
                    response += f" ({release_year})"
                except ValueError:
                    pass
            
            response += "\n"
            
            rating = movie.get('rating')
            if rating:
                response += f"   Rating: {rating}/10\n"
            
            response += f"   {movie.get('overview', 'No description available.')[:150]}...\n"
            
            theaters = movie.get('theaters', [])
            if theaters:
                response += "\n   Showing at:\n"
                for theater in theaters[:3]:  # Limit to 3 theaters
                    response += f"   - {theater.get('name', 'Unknown theater')}\n"
                
                # Add showtimes for the first theater
                if theaters and theaters[0].get('showtimes'):
                    response += "   Today's showtimes: "
                    today_showtimes = [
                        datetime.fromisoformat(st.get('start_time')).strftime("%I:%M %p")
                        for st in theaters[0].get('showtimes', [])
                        if datetime.fromisoformat(st.get('start_time')).date() == datetime.now().date()
                    ]
                    response += ", ".join(today_showtimes[:4])  # Limit to 4 showtimes
                    response += "\n"
            
            response += "\n"
        
        response += "Would you like more details about any of these movies, or would you like to see other options?"
        
        return response
