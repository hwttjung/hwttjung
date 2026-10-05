
<!DOCTYPE html>
<html lang="en">

<head>
    <title>RSS - The New York Times</title>
    <script id="nyt-capsule-data" type="text/json">
        {
            "lastTransform": "2018-06-21T18:56:36.586Z"
        }
    </script>
    <script src="https://archive.nytimes.com/_capsule/nyt-capsule.js" type="text/javascript"></script>
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <meta name="robots" content="noarchive">
    <meta name="description" content="Subscribe to RSS feeds from The New York Times.">
    <meta name="CG" content="Member Center">
    <meta name="SCG" content="">
    <meta name="PT" content="Member Center">
    <meta name="PST" content="RSS Page">
    <meta name="PSST" content="">
    <meta name="PS" content="">
    <meta name="ttl" content="">
    <link rel="stylesheet" type="text/css" href="https://static01.nyt.com/css/0.1/screen/build/rss/styles.css">
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/jquery/jquery-1.6.2.min.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/jquery/jquery-ui-1.8.16.min.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/common.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/common/screen/DropDown.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/util/tooltip.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/prototype/1.6.0.2/prototype.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/scriptaculous/1.8.1/effects.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/scriptaculous/1.8.1/controls.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/NYTD/0.0.1/accordion.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/controls/restful_autocompleter.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/rss/rssAutocompleter.js"></script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/lib/NYTD/0.0.1/showhide.js"></script>
    <link rel="stylesheet" type="text/css" href="https://archive.nytimes.com/_capsule/nyt-capsule.css">
</head>

<body>
    <a name="top"></a>
    <div id="shell">
        <div class="mainTabsContainer tabsContainer">
            <ul id="mainTabs" class="mainTabs tabs">
                <li class="first mainTabHome"><a href="https://www.nytimes.com">Home Page</a></li>
                <li class="mainTabTodaysPaper"><a href="https://www.nytimes.com/pages/todayspaper/index.html">Today&apos;s Paper</a></li>
                <li class="mainTabVideo"><a href="https://www.nytimes.com/video">Video</a></li>
                <li class="mainTabMostPopular"><a href="https://www.nytimes.com/most-popular">Most Popular</a></li>
            </ul>
        </div>
        <div id="editionToggle" class="editionToggle">
            Edition: <span id="editionToggleUS"><a href="https://www.nytimes.com" onmousedown="dcsMultiTrack(&apos;DCS.dcssip&apos;,&apos;www.nytimes.com&apos;,&apos;DCS.dcsuri&apos;,&apos;/toggleIHTtoNYT.html&apos;,&apos;WT.ti&apos;,&apos;toggleIHTtoNYT&apos;,&apos;WT.z_dcsm&apos;,&apos;1&apos;);" onclick="NYTD.EditionPref.setUS();">U.S.</a></span>            / <span id="editionToggleGlobal"><a href="http://global.nytimes.com/" onmousedown="dcsMultiTrack(&apos;DCS.dcssip&apos;,&apos;www.nytimes.com&apos;,&apos;DCS.dcsuri&apos;,&apos;/toggleNYTtoIHT.html&apos;,&apos;WT.ti&apos;,&apos;toggleNYTtoIHT&apos;,&apos;WT.z_dcsm&apos;,&apos;1&apos;);" onclick="NYTD.EditionPref.setGlobal();">Global</a></span>
        </div>
        <script type="text/javascript">
            NYTD.loadEditionToggle();

            window.setTimeout(function() {
                var login = document.getElementById('memberToolsLogin');
                if (login) {
                    login.href += "?URI=" + window.location.href;
                }
            }, 0)
        </script>
        <div id="page" class="tabContent active">
            <div class="clearfix" id="masthead">
                <div id="searchWidget">
                    <div class="inlineSearchControl">
                        <form enctype="application/x-www-form-urlencoded" action="https://query.nytimes.com/search/sitesearch" method="get" name="searchForm" id="searchForm">
                            <input type="hidden" value="full" name="date_select">
                            <label for="searchQuery">Search All NYTimes.com</label>
                            <input type="text" class="text" value="" size="" name="query" id="searchQuery">
                            <input type="hidden" id="searchAll" name="type" value="nyt">
                            <input type="image" id="searchSubmit" title="Search" alt="Search" width="22" height="19" src="https://static01.nyt.com/images/global/buttons/go.gif">
                        </form>
                    </div>
                </div>
                <div id="branding" itemscope="" itemtype="http://schema.org/Organization">
                    <a href="https://www.nytimes.com" itemprop="url"><img src="https://static01.nyt.com/images/misc/nytlogo152x23.gif" alt="New York Times" id="NYTLogo" itemprop="logo"></a>
                </div>
                <div id="date">
                    <p>
                        Friday, January 5, 2018 </p>
                </div>
                <h2>
                    <a href="https://www.nytimes.com/services/xml/rss/index.html">RSS</a>
                </h2>
            </div>
            <div></div>
            <div class="navigation tabsContainer">
                <ul class="tabs">
                    <li id="navWorld" class="first ">
                        <a href="https://www.nytimes.com/pages/world/index.html">World</a>
                    </li>
                    <li id="navUs">
                        <a href="https://www.nytimes.com/pages/national/index.html">U.S.</a>
                    </li>
                    <li id="navNyregion">
                        <a href="https://www.nytimes.com/pages/nyregion/index.html">N.Y. / Region</a>
                    </li>
                    <li id="navBusiness">
                        <a href="https://www.nytimes.com/pages/business/index.html">Business</a>
                    </li>
                    <li id="navTechnology">
                        <a href="https://www.nytimes.com/pages/technology/index.html">Technology</a>
                    </li>
                    <li id="navScience">
                        <a href="https://www.nytimes.com/pages/science/index.html">Science</a>
                    </li>
                    <li id="navHealth">
                        <a href="https://www.nytimes.com/pages/health/index.html">Health</a>
                    </li>
                    <li id="navSports">
                        <a href="https://www.nytimes.com/pages/sports/index.html">Sports</a>
                    </li>
                    <li id="navOpinion">
                        <a href="https://www.nytimes.com/pages/opinion/index.html">Opinion</a>
                    </li>
                    <li id="navArts">
                        <a href="https://www.nytimes.com/pages/arts/index.html">Arts</a>
                    </li>
                    <li id="navStyle">
                        <a href="https://www.nytimes.com/pages/style/index.html">Style</a>
                    </li>
                    <li id="navTravel">
                        <a href="https://www.nytimes.com/pages/travel/index.html">Travel</a>
                    </li>
                    <li id="navJobs">
                        <a href="https://www.nytimes.com/pages/jobs/index.html">Jobs</a>
                    </li>
                    <li id="navRealestate">
                        <a href="https://www.nytimes.com/pages/realestate/index.html">Real Estate</a>
                    </li>
                    <li id="navAutomobiles">
                        <a href="https://www.nytimes.com/pages/automobiles/index.html">Autos</a>
                    </li>
                </ul>
            </div>
            <div id="main">
                <div class="spanAB wrap">
                    <div class="abColumn">
                        <div class="columnGroup first">
                            <div class="rssIntro ">
                                <p><span class="rssTitle">RSS</span> (Really Simple Syndication) feeds offer another way to get NYTimes.com content. Subscribe to our feeds to get the latest headlines, summaries and links back to full articles - formatted
                                    for your favorite feed reader and updated throughout the day.
                                </p>
                            </div>
                            <div id="rss-toggler" class="toggler">
                                <div class="columnGroup doubleRule">
                                    <div class="columnGroup">
                                        <div class="rssGroup">
                                            <p>News</p>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml">
							     	 		<span class="rssRow">NYTimes.com Home Page (U.S.)</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">World</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/World.xml">World</a>
                                                            <ul class="rssSubsection">
                                                            </ul>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Africa.xml">Africa</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Americas.xml">Americas</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/AsiaPacific.xml">Asia Pacific</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Europe.xml">Europe</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml">Middle East</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">U.S.</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/US.xml">U.S.</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Education.xml">Education</a>
                                                            <ul class="rssSubsection">
                                                            </ul>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml">Politics</a>
                                                            <ul class="rssSubsection">
                                                                <li class="last"><a href="https://rss.nytimes.com/services/xml/rss/nyt/Upshot.xml">The Upshot</a>
                                                                </li>
                                                            </ul>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/NYRegion.xml">
							     	 		<span class="rssRow">N.Y./Region</span>

				     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Business</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Business.xml">Business</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/EnergyEnvironment.xml">Energy &amp; Environment</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/SmallBusiness.xml">Small Business</a>
                                                            <ul class="rssSubsection">
                                                            </ul>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml">Economy</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Dealbook.xml">DealBook</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/MediaandAdvertising.xml">Media &amp; Advertising</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/YourMoney.xml">Your Money</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Technology</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="	https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml">Technology</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/PersonalTech.xml">Personal Tech</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Sports</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml">Sports</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Baseball.xml">Baseball</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/CollegeBasketball.xml">College Basketball</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/CollegeFootball.xml">College Football</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Golf.xml">Golf</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Hockey.xml">Hockey</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/ProBasketball.xml">Pro-Basketball</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/ProFootball.xml">Pro-Football</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Soccer.xml">Soccer</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Tennis.xml">Tennis</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Science</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Science.xml">Science</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Climate.xml">Environment</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Space.xml">Space &amp; Cosmos</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Health</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://www.nytimes.com/services/xml/rss/nyt/Health.xml">Health</a>
                                                            <ul class="rssSubsection">
                                                                <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Well.xml">Well Blog</a>
                                                                </li>
                                                            </ul>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="singleRuleDivider"></div>
                                </div>
                                <div class="columnGroup doubleRule">
                                    <div class="columnGroup">
                                        <div class="rssGroup">
                                            <p>Culture &amp; Lifestyle</p>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Arts</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml">Arts</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/ArtandDesign.xml">Art &amp; Design</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Books.xml">Books</a>
                                                            <ul class="rssSubsection">
                                                                <li class="last"><a href="https://rss.nytimes.com/services/xml/rss/nyt/SundayBookReview.xml">Sunday Book Review</a>
                                                                </li>
                                                            </ul>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Dance.xml">Dance</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Movies.xml">Movies</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Music.xml">Music</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Television.xml">Television</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/Theater.xml">Theater</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Style</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/FashionandStyle.xml">Fashion &amp; Style</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/DiningandWine.xml">Dining &amp; Wine</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="https://www.nytimes.com/services/xml/rss/nyt/Weddings.xml">Love</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="https://rss.nytimes.com/services/xml/rss/nyt/tmagazine.xml">T Magazine</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://www.nytimes.com/services/xml/rss/nyt/Travel.xml">
							     	 		<span class="rssRow">Travel</span>

				     									        </a>
                                        </div>
                                    </div>
                                    <div class="singleRuleDivider"></div>
                                </div>
                                <div class="columnGroup doubleRule">
                                    <div class="columnGroup">
                                        <div class="rssGroup">
                                            <p>Marketplace</p>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/Jobs.xml">
							     	 		<span class="rssRow">Jobs</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/RealEstate.xml">
							     	 		<span class="rssRow">Real Estate</span>

				     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/Automobiles.xml">
							     	 		<span class="rssRow">Autos</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="singleRuleDivider"></div>
                                </div>
                                <div class="columnGroup doubleRule">
                                    <div class="columnGroup">
                                        <div class="rssGroup">
                                            <p>Other</p>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/Lens.xml">
							     	 		<span class="rssRow">Lens Blog</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/Obituaries.xml">
							     	 		<span class="rssRow">Obituaries</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="http://nytimes.com/timeswire/feeds/">
							     	 		<span class="rssRow">Times Wire</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/MostEmailed.xml">
							     	 		<span class="rssRow">Most E-Mailed</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/MostShared.xml">
							     	 		<span class="rssRow">Most Shared</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/MostViewed.xml">
							     	 		<span class="rssRow">Most Viewed</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="singleRuleDivider"></div>
                                </div>
                                <div class="columnGroup doubleRule">
                                    <div class="columnGroup">
                                        <div class="rssGroup">
                                            <p>Opinion</p>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a class="suppressed" href="javascript:void(0);">
							     	 		<span class="rssRow">Columnists</span>

								     									     	    								        		<span class="rssCount"></span>
								        									        								        </a>
                                        </div>
                                        <div class="rssExtra">
                                            <div class="subColumn-3 insetRSS">
                                                <div class="singleRuleDivider"></div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/charles-m-blow/rss.xml">Charles M. Blow</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/david-brooks/rss.xml">David Brooks</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/frank-bruni/rss.xml">Frank Bruni</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://topics.nytimes.com/top/news/international/columns/rogercohen/index.html?rss=1">Roger Cohen</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/gail-collins/rss.xml">Gail Collins</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/ross-douthat/rss.xml">Ross Douthat</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/maureen-dowd/rss.xml">Maureen Dowd</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/thomas-l-friedman/rss.xml">Thomas L. Friedman</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                                <div class="column">
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/nicholas-kristof/rss.xml">Nicholas D. Kristof</a>
                                                        </li>
                                                    </ul>
                                                    <ul class="rssColumns">
                                                        <li><a href="http://www.nytimes.com/svc/collections/v1/publish/www.nytimes.com/column/paul-krugman/rss.xml">Paul Krugman</a>
                                                        </li>
                                                    </ul>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="columnGroup singleRule ">
                                        <div class="rssSection">
                                            <a href="https://rss.nytimes.com/services/xml/rss/nyt/sunday-review.xml">
							     	 		<span class="rssRow">Sunday Review</span>

								     									        </a>
                                        </div>
                                    </div>
                                    <div class="singleRuleDivider"></div>
                                </div>
                                <div class="rssFooterHeader">
                                    <p>Terms &amp; Conditions</p>
                                </div>
                                <div class="rssFooter">
                                    <p>We encourage the use of NYTimes.com RSS feeds for personal use in a news reader or as part of a non- commercial blog. We require proper format and attribution whenever New York Times content is posted on your web site,
                                        and we reserve the right to require that you cease distributing NYTimes.com content. Please read the <a href="https://www.nytimes.com/services/xml/rss/termsconditions.html"><span class="termcondition">Terms and Conditions</span></a>                                        for complete instructions. </p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="cColumn"></div>
                </div>
            </div>
            <footer class="pageFooter">
                <div class="inset">
                    <nav class="pageFooterNav">
                        <ul class="pageFooterNavList wrap">
                            <li class="firstItem"><a href="https://www.nytimes.com/content/help/rights/copyright/copyright-notice.html">&#xA9; 2018 The New York Times Company</a></li>
                            <li><a href="http://spiderbites.nytimes.com/">Site Map</a></li>
                            <li><a href="https://www.nytimes.com/privacy">Privacy</a></li>
                            <li><a href="https://www.nytimes.com/ref/membercenter/help/privacy.html#pp">Your Ad Choices</a></li>
                            <li><a href="http://www.nytimes.whsites.net/mediakit/">Advertise</a></li>
                            <li><a href="https://www.nytimes.com/content/help/rights/sale/terms-of-sale.html ">Terms of Sale</a></li>
                            <li><a href="https://www.nytimes.com/ref/membercenter/help/agree.html">Terms of Service</a></li>
                            <li><a href="http://www.nytco.com/careers">Work With Us</a></li>
                            <li><a href="https://www.nytimes.com/rss">RSS</a></li>
                            <li><a href="https://www.nytimes.com/membercenter/sitehelp.html">Help</a></li>
                            <li><a href="https://www.nytimes.com/ref/membercenter/help/infoservdirectory.html">Contact Us</a></li>
                            <li class="lastItem"><a href="https://myaccount.nytimes.com/membercenter/feedback.html">Site Feedback</a></li>
                        </ul>
                    </nav>
                </div>
            </footer>
        </div>
    </div>
    <script type="text/javascript">
        var dcsvid = "";
        var regstatus = "non-registered";
    </script>
    <script type="text/javascript" src="https://static01.nyt.com/js/app/rss/rssFooter.js"></script>
</body>