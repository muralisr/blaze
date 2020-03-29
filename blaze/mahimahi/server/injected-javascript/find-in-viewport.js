var imagesInViewPort = []
var speedIndex = {}


function getViewportSize() {
    var windowRight = window.innerWidth ? window.innerWidth : document.documentElement.clientWidth;
    var windowHeight = window.innerHeight ? window.innerHeight : document.documentElement.clientHeight;
    return windowHeight * windowRight;
}

function isElementInViewport (el) {
    //special bonus for those using jQuery
    if (typeof jQuery === "function" && el instanceof jQuery) {
        el = el[0];
    }
    var rect = el.getBoundingClientRect();
    var topIsVisible = rect.top >= 0 && (rect.top <= (window.innerHeight || document.documentElement.clientHeight));
	var botIsVisible = rect.top < 0 && rect.bottom >= 0;
	var vertInView = topIsVisible || botIsVisible;

	var leftIsVisible = rect.left >= 0 && (rect.left <= (window.innerWidth || document.documentElement.clientWidth));
	var rightIsVisible = rect.left < 0 && rect.right >= 0;
	var horzInView = leftIsVisible || rightIsVisible;

	return vertInView && horzInView;
}

function getSpeedIndexContribution(node) {
    
    if(!isElementInViewport(node)) {
        return 0;
    }
    // given a node, we need to find out the area visible in the viewport

    
    var rect = node.getBoundingClientRect();

    // if image x is > 0, then left top x is image.x
    var leftTopX = rect.x > 0 ? rect.x : 0;

    // if image y is > 0, then left top y is image.y
    var leftTopY = rect.y > 0 ? rect.y : 0;
    
    // if image x is < viewport.width, then right bottom x is image.x
    var windowRight = window.innerWidth ? window.innerWidth : document.documentElement.clientWidth;
    var rightBottomX = rect.right < windowRight ? rect.right : windowRight;
    
    // if image y is < viewport.height, then right bottom y is image.y
    var windowHeight = window.innerHeight ? window.innerHeight : document.documentElement.clientHeight;
    var rightBottomY = rect.bottom < windowHeight ? rect.bottom : windowHeight;


    var lengthOfRectangle = rightBottomX - leftTopX;
    var heightOfRectangle = rightBottomY - leftTopY;

    // here, we should divide by the total occupied viewport size
    // we will know this once we finish populating the speedIndex array
    // i.e. once we know area of each element in viewport. so it is done later
    // in normalizedSpeedIndex. there, we know the total occupied area
    // then, each element's respective contribution can be computed
    // console.log("returning speed index contribution as ", lengthOfRectangle * heightOfRectangle)
    return lengthOfRectangle * heightOfRectangle;
}


function getCriticalRequests() {
    var importantRequests = []
    importantRequests = imagesInViewPort.map(function(url) {return url;});
    if (typeof(urlRequestors) == 'undefined' || urlRequestors == null) return importantRequests;
    urlRequestors.forEach(function(k) {
        if (imagesInViewPort.indexOf(k.url) >= 0) {
            importantRequests = importantRequests.concat(k.initiator)
        }
    })
    return importantRequests
}

function normalizeSpeedIndices(speedIndexLocal) {
    // speedIndexLocal is a dict of url -> viewport area 
    // for each element, we divide by the total occupied viewport area
    var totalArea = 0;
    for (var key in speedIndexLocal) {
        if (speedIndexLocal.hasOwnProperty(key)) {
            totalArea = totalArea + speedIndexLocal[key];
        }
    }
    if (totalArea == 0) {
        totalArea = 1;
    }
    for (var key in speedIndexLocal) {
        if (speedIndexLocal.hasOwnProperty(key)) {
            var currentValue = speedIndexLocal[key];
            var newValue = currentValue * 1.0 / totalArea;
            speedIndexLocal[key] = newValue;
        }   
    }
    return speedIndexLocal
}

function getSpeedIndicesOfElementsInViewport() {
    // speedIndex is a global variable.
    // if we have not intercepted any javascript, just return compute speedindex for images
    if (typeof(urlRequestors) == 'undefined' || urlRequestors == null) return normalizeSpeedIndices(speedIndex);
    // for each js file
    urlRequestors.forEach(function(k) {
        // if it has sent any image to the viewport
        if (imagesInViewPort.indexOf(k.url) >= 0) {
            // we assign the javascript file a speedindex value equal to the image it sent to the viewport
            speedIndex[k.initiator] = speedIndex[k.url];
        }
    })
    return normalizeSpeedIndices(speedIndex)
}


function findAndPrintImagesInViewport(ele) {
    ele.querySelectorAll('*').forEach(function(node) {
        try {
            if (isElementInViewport(node)) {
                var url = null;
                if(node.tagName == "IMG") {
                    if (typeof node.href != 'undefined') {
                        url = node.href;
                    }
                    if(typeof node.src != 'undefined') {
                        url = node.src;
                    }
                    if (url != null) {
                        imagesInViewPort.push(url)
                        speedIndex[url] = getSpeedIndexContribution(node);
                    }
            } else {
                var style = window.getComputedStyle(node)
                for (var i = style.length - 1; i >= 0; i--) {
                    var cssName = style[i]
                    var cssPropertyValue = style.getPropertyValue(cssName)
                    if (cssPropertyValue.indexOf("url") >= 0) {
                        var potentialURL = cssPropertyValue;
                        var startIndex = potentialURL.indexOf('url(')
                        var urlWithSpace = false;
                        if (startIndex < 0) {
                            startIndex = potentialURL.indexOf('url (')
                            urlWithSpace = true;
                        } 
                        if (startIndex < 0) {
                            continue;
                        }
                        var endIndex = potentialURL.indexOf(')', startIndex)
                        if (endIndex < 0) {
                            continue
                        }
                        var potentialURL = potentialURL.substring(startIndex + (urlWithSpace ? 5 : 4), endIndex)
                        var t=potentialURL.length;
                        if (potentialURL.charAt(0)=='"'||potentialURL.charAt(0)=="'") {
                            potentialURL = potentialURL.substring(1);
                            t--;
                        }
                        if (potentialURL.charAt(t-1)=='"'||potentialURL.charAt(t-1)=="'") {
                            potentialURL = potentialURL.substring(0,t-1);
                        }
    
                        var link = document.createElement("a");
                        link.href = potentialURL;
                        if(potentialURL.index("data:image") < 0)
                            imagesInViewPort.push(link.href)
                            speedIndex[link.href] = getSpeedIndexContribution(node);
                    }
                }
            }  
            }           
        } catch (error) {
            // console.error("ignoring node due to error ", error)
        }

    });
    var critical_requests = getCriticalRequests()
    var speed_indices = getSpeedIndicesOfElementsInViewport()
    console.log(JSON.stringify({'alohomora_output': critical_requests, 'speed_index': speed_indices}))
}


window.addEventListener('load', function (event) {
    try {
        findAndPrintImagesInViewport(document)
        var listOfIframes = document.querySelectorAll("iframe");
        for (var index = 0; listOfIframes && index < listOfIframes.length; index++) {
            const iframeElement = listOfIframes[index];
            if(typeof(iframeElement) == 'undefined') {
                continue;
            }
            if(iframeElement && isElementInViewport(iframeElement)) {
                try {
                    var innerDoc = (iframeElement.contentDocument) ? iframeElement.contentDocument : iframeElement.contentWindow.document;    
                    findAndPrintImagesInViewport(innerDoc)
                } catch (error) {
                    console.error('avoid processing iframe due to an exception ', error)
                }
            }
        }    
    } catch (error) {
        console.error("skipping due to error ", error)
    }    
  });

